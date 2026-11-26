// 在独立 AutoCAD Core Console 中只读源库，不加载或改写用户正在编辑的图纸。
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Globalization;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(QxTerrainFilter.Commands))]
namespace QxTerrainFilter
{
    public class Commands
    {
        const string ProvenanceApp = "QX_TERRAIN_SOURCE";
        static void Count(Dictionary<string, int> counts, string key)
        { int old; counts.TryGetValue(key, out old); counts[key] = old + 1; }

        sealed class Label { public string Handle; public Point3d Position; public double Value; }
        static string Cell(double x,double y) { return Math.Floor(x / 3.0).ToString("R",CultureInfo.InvariantCulture)+","+Math.Floor(y / 3.0).ToString("R",CultureInfo.InvariantCulture); }
        static Dictionary<string,object> CircleMarkers(BlockTableRecord model,Transaction transaction)
        {
            var labels=new Dictionary<string,List<Label>>();var circles=new List<Circle>();
            foreach(ObjectId id in model)
            {
                var entity=transaction.GetObject(id,OpenMode.ForRead) as Entity;
                if(entity==null || !String.Equals(entity.Layer,"GCD",StringComparison.OrdinalIgnoreCase))continue;
                var text=entity as DBText;var circle=entity as Circle;
                double number;
                if(text!=null && Double.TryParse(text.TextString.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out number) && !Double.IsNaN(number) && !Double.IsInfinity(number))
                {
                    string key=Cell(text.Position.X,text.Position.Y);List<Label> cell;
                    if(!labels.TryGetValue(key,out cell)){cell=new List<Label>();labels[key]=cell;}
                    cell.Add(new Label{Handle=text.Handle.ToString(),Position=text.Position,Value=number});
                }
                else if(circle!=null && circle.Radius>0 && circle.Radius<=0.5 && Math.Abs(Math.Abs(circle.Normal.Z)-1)<1e-10)circles.Add(circle);
            }
            var matches=new Dictionary<string,object>();
            foreach(var circle in circles)
            {
                var center=circle.Center;Label best=null;double bestDistance=Double.PositiveInfinity;
                for(int dx=-1;dx<=1;dx++)for(int dy=-1;dy<=1;dy++)
                {
                    List<Label> near;if(!labels.TryGetValue(Cell(center.X+3*dx,center.Y+3*dy),out near))continue;
                    foreach(var label in near)
                    {
                        double x=label.Position.X-center.X,y=label.Position.Y-center.Y,distance=Math.Sqrt(x*x+y*y);
                        if(distance<=3 && Math.Abs(label.Value-center.Z)<=0.051 && distance<bestDistance){best=label;bestDistance=distance;}
                    }
                }
                if(best!=null)matches[circle.Handle.ToString()]=new{handle=best.Handle,xyz=new[]{best.Position.X,best.Position.Y,best.Position.Z},text_elevation=best.Value,distance_xy_m=bestDistance,circle_xyz=new[]{center.X,center.Y,center.Z},text_geometry_z_difference_m=best.Position.Z-center.Z};
            }
            // 仅完整的 GCD 测点符号图式启用圆心模式，不泛化为所有圆。
            return matches.Count>=3 && matches.Count>=0.9*circles.Count ? matches : new Dictionary<string,object>();
        }

        [CommandMethod("QXTERRAINFILTER", CommandFlags.Session)]
        public void Filter()
        {
            string configPath = Environment.GetEnvironmentVariable("QX_TERRAIN_FILTER_CONFIG");
            var json = new JavaScriptSerializer(); json.MaxJsonLength = Int32.MaxValue;
            var config = json.Deserialize<Dictionary<string, string>>(File.ReadAllText(configPath, Encoding.UTF8));
            string output = config["output"], reportPath = config["report"];
            var report = new Dictionary<string, object>();
            try
            {
                var sourceCounts = new Dictionary<string, int>();
                var contourIds = new ObjectIdCollection();
                var elevations = new List<Tuple<Point3d, string>>();
                var elevationKinds=new Dictionary<string,string>();var circleMarkers=new Dictionary<string,object>();
                var gcdContourHandles=new HashSet<string>();
                int scanned = 0, contourVertices = 0, curvedContours = 0, widthCleared = 0;
                using (var source = new Database(false, true))
                using (var target = new Database(true, true))
                {
                    // 工作副本仅允许读共享，禁止其他写入者造成延迟读取不一致。
                    source.ReadDwgFile(config["source"], FileOpenMode.OpenForReadAndReadShare, true, "");
                    using (var transaction = source.TransactionManager.StartTransaction())
                    {
                        var blocks = (BlockTable)transaction.GetObject(source.BlockTableId, OpenMode.ForRead);
                        var model = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                        circleMarkers=CircleMarkers(model,transaction);
                        foreach (ObjectId id in model)
                        {
                            var entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
                            if (entity == null) continue;
                            scanned++; string layer = entity.Layer.ToUpperInvariant();
                            Count(sourceCounts, layer + "/" + id.ObjectClass.DxfName);
                            var block = entity as BlockReference;
                            var circle=entity as Circle;
                            if (layer == "GCD" && block != null)
                            {
                                // Position 是 WCS 插入点；不炸块、不读文字、不从 GC200 等块名猜高程。
                                elevations.Add(Tuple.Create(block.Position, entity.Handle.ToString()));
                                elevationKinds[entity.Handle.ToString()]="GCD_INSERT";
                            }
                            else if(layer=="GCD" && circle!=null && circleMarkers.ContainsKey(entity.Handle.ToString()))
                            {
                                elevations.Add(Tuple.Create(circle.Center,entity.Handle.ToString()));
                                elevationKinds[entity.Handle.ToString()]="GCD_CIRCLE_CENTER";
                            }
                            else if ((layer == "SQX" || layer == "JQX" || circleMarkers.Count>0 && layer=="GCD" && (entity is Polyline || entity is Polyline2d || entity is Polyline3d)) && entity is Curve
                                     && !(entity is Ray) && !(entity is Xline))
                            {
                                contourIds.Add(id);
                                if(layer=="GCD")gcdContourHandles.Add(entity.Handle.ToString());
                                var polyline = entity as Polyline;
                                if (polyline != null) contourVertices += polyline.NumberOfVertices + (polyline.Closed ? 1 : 0);
                                else if (entity is Polyline2d || entity is Polyline3d)
                                {
                                    if (entity is Polyline2d) foreach (ObjectId vertex in (Polyline2d)entity) contourVertices++;
                                    else foreach (ObjectId vertex in (Polyline3d)entity) contourVertices++;
                                    if (((Curve)entity).Closed) contourVertices++;
                                }
                                else curvedContours++;
                            }
                        }
                        transaction.Commit();
                    }
                    report["scanned_model_entities"] = scanned; report["source_layer_types"] = sourceCounts;
                    report["gcd_insert_count"] = elevations.Count; report["contour_count"] = contourIds.Count;
                    if (contourIds.Count + elevations.Count == 0) throw new InvalidOperationException("GCD 块参照及 SQX/JQX 等高线均为空");
                    ObjectId targetModel;
                    using (var transaction = target.TransactionManager.StartTransaction())
                    {
                        var blocks = (BlockTable)transaction.GetObject(target.BlockTableId, OpenMode.ForRead);
                        targetModel = blocks[BlockTableRecord.ModelSpace];
                        transaction.Commit();
                    }
                    // 克隆原等高线，完整保留高程、闭合标志、圆弧和样条，不作抽稀。
                    var contourMapping = new IdMapping();
                    var originalContourHandles = new Dictionary<ObjectId, string>();
                    if (contourIds.Count > 0)
                    {
                        source.WblockCloneObjects(contourIds, targetModel, contourMapping, DuplicateRecordCloning.Ignore, false);
                        var originals = new HashSet<ObjectId>();
                        foreach (ObjectId id in contourIds) originals.Add(id);
                        foreach (IdPair pair in contourMapping)
                            if (pair.IsCloned && originals.Contains(pair.Key))
                                originalContourHandles[pair.Value] = pair.Key.Handle.ToString();
                    }
                    using (var transaction = target.TransactionManager.StartTransaction())
                    using (var provenance = new StreamWriter(config["points"], false, new UTF8Encoding(false)))
                    {
                        var layers = (LayerTable)transaction.GetObject(target.LayerTableId, OpenMode.ForRead);
                        if (!layers.Has("GCD"))
                        { layers.UpgradeOpen(); var layer = new LayerTableRecord { Name = "GCD" }; layers.Add(layer); transaction.AddNewlyCreatedDBObject(layer, true); }
                        if(gcdContourHandles.Count>0 && !layers.Has("SQX"))
                        { layers.UpgradeOpen();var layer=new LayerTableRecord{Name="SQX"};layers.Add(layer);transaction.AddNewlyCreatedDBObject(layer,true); }
                        var apps = (RegAppTable)transaction.GetObject(target.RegAppTableId, OpenMode.ForWrite);
                        if (!apps.Has(ProvenanceApp))
                        { var app = new RegAppTableRecord { Name = ProvenanceApp }; apps.Add(app); transaction.AddNewlyCreatedDBObject(app, true); }
                        var model = (BlockTableRecord)transaction.GetObject(targetModel, OpenMode.ForWrite);
                        foreach (ObjectId id in model)
                        {
                            var entity = transaction.GetObject(id, OpenMode.ForWrite) as Entity;
                            if (!(entity is Curve)) continue;
                            string originalHandle;
                            if (originalContourHandles.TryGetValue(id, out originalHandle))
                            {
                                string originalLayer=entity.Layer.ToUpperInvariant();
                                using (var data = new ResultBuffer(new TypedValue(1001, ProvenanceApp), new TypedValue(1000, "CONTOUR_CENTERLINE"), new TypedValue(1000, originalHandle),new TypedValue(1000,originalLayer))) entity.XData = data;
                                if(gcdContourHandles.Contains(originalHandle))entity.LayerId=layers["SQX"];
                            }
                            // 宽度属于显示属性：只输出中心线，防止 Rhino 将宽多段线展开为两侧轮廓。
                            entity.LineWeight = LineWeight.LineWeight000;
                            bool hadWidth = false;
                            var line = entity as Polyline;
                            if (line != null)
                            {
                                // 变宽多段线读取 ConstantWidth 会抛 eInvalidInput，逐顶点读宽即可。
                                for (int index = 0; index < line.NumberOfVertices; index++)
                                {
                                    hadWidth |= line.GetStartWidthAt(index) != 0 || line.GetEndWidthAt(index) != 0;
                                    line.SetStartWidthAt(index, 0); line.SetEndWidthAt(index, 0);
                                }
                                line.ConstantWidth = 0;
                            }
                            var oldLine = entity as Polyline2d;
                            if (oldLine != null)
                            {
                                hadWidth = oldLine.DefaultStartWidth != 0 || oldLine.DefaultEndWidth != 0;
                                oldLine.DefaultStartWidth = 0; oldLine.DefaultEndWidth = 0;
                                foreach (ObjectId vertexId in oldLine)
                                {
                                    var vertex = (Vertex2d)transaction.GetObject(vertexId, OpenMode.ForWrite);
                                    hadWidth |= vertex.StartWidth != 0 || vertex.EndWidth != 0;
                                    vertex.StartWidth = 0; vertex.EndWidth = 0;
                                }
                            }
                            if (hadWidth) widthCleared++;
                            var layerRecord = (LayerTableRecord)transaction.GetObject(entity.LayerId, OpenMode.ForWrite);
                            layerRecord.LineWeight = LineWeight.LineWeight000;
                        }
                        foreach (var item in elevations)
                        {
                            // 指定目标库的图层 ID，避免未入库实体按当前文档解析同名图层。
                            var point = new DBPoint(item.Item1) { LayerId = layers["GCD"], LineWeight = LineWeight.LineWeight000 };
                            model.AppendEntity(point); transaction.AddNewlyCreatedDBObject(point, true);
                            using (var data = new ResultBuffer(new TypedValue(1001, ProvenanceApp), new TypedValue(1000, elevationKinds[item.Item2]), new TypedValue(1000, item.Item2),new TypedValue(1000,"GCD"))) point.XData = data;
                            object label;circleMarkers.TryGetValue(item.Item2,out label);
                            provenance.WriteLine(json.Serialize(new { handle = item.Item2, xyz = new double[] { item.Item1.X, item.Item1.Y, item.Item1.Z },source_kind=elevationKinds[item.Item2],label_evidence=label }));
                        }
                        transaction.Commit();
                    }
                    target.Insunits = source.Insunits;
                    target.DxfOut(output, 16, DwgVersion.AC1027);
                    report["source_insunits"] = (int)source.Insunits;
                }
                report["passed"] = true; report["scanned_model_entities"] = scanned;
                report["source_layer_types"] = sourceCounts; report["gcd_insert_count"] = elevations.Count;
                report["contour_count"] = contourIds.Count; report["contour_vertex_count"] = contourVertices;
                report["curved_contour_count"] = curvedContours;
                report["width_cleared_contours"] = widthCleared;
                report["point_count_lower_bound"] = elevations.Count + contourVertices;
                report["gcd_circle_center_count"]=circleMarkers.Count;report["gcd_circle_label_evidence"]=circleMarkers;
                report["source_layout"]=circleMarkers.Count>0 ? "gcd_circle_markers_with_gcd_contours" : "gcd_inserts_sqx_jqx";
            }
            catch (System.Exception error) { report["passed"] = false; report["error"] = error.ToString(); }
            File.WriteAllText(reportPath, json.Serialize(report), new UTF8Encoding(false));
        }
    }
}
