using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;
using System.Linq;
using System.Web.Script.Serialization;
using System.Security.Cryptography;

// File3dm/OpenNURBS only: no RhinoCore, UI, remeshing, or volume boolean.
public static class TerrainMeshReader
{
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    public static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush=true });
        try
        {
            SetDllDirectory(AppDomain.CurrentDomain.BaseDirectory);
            if(args.Length==2 && args[0]=="--append-meshes") return AppendMeshes(args[1]);
            if(args.Length==2 && args[0]=="--write-precision-control")
                return WritePrecisionControl(args[1]);
            if(args.Length < 3) throw new ArgumentException("system-path input.3dm output.bin [mesh-index]");
            // Retain the three-argument interface. The first argument is ignored:
            // dependencies are the bundled MIT Rhino3dm/OpenNURBS distribution,
            // never RhinoCommon or the user's Rhino installation.
            SetDllDirectory(AppDomain.CurrentDomain.BaseDirectory);
            return Read(args);
        }
        catch(Exception e) { Console.Error.WriteLine(e.ToString()); return 1; }
    }

    public sealed class WriteJob
    {
        public string schema_version;public string source;public string output;
        public Dictionary<string,string> document_strings;public List<MeshSpec> meshes;
    }
    public sealed class MeshSpec
    {
        public string binary_path;public string name;public string layer;
        public int[] color;public Dictionary<string,string> user_strings;public bool require_closed;
    }
    static string HashFile(string path)
    {using(var input=File.OpenRead(path))using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant();}
    static void ExactMesh(Rhino.Geometry.Mesh before,Rhino.Geometry.Mesh after,string label)
    {
        if(before.Vertices.Count!=after.Vertices.Count || before.Faces.Count!=after.Faces.Count)throw new IOException(label+" saved counts changed");
        for(int i=0;i<before.Vertices.Count;i++)if(before.Vertices.Point3dAt(i)!=after.Vertices.Point3dAt(i))throw new IOException(label+" saved double XYZ changed at "+i);
        for(int i=0;i<before.Faces.Count;i++)if(before.Faces[i]!=after.Faces[i])throw new IOException(label+" saved face indices changed at "+i);
    }
    static Rhino.Geometry.Mesh ReadBinaryMesh(string path)
    {
        var mesh=new Rhino.Geometry.Mesh();mesh.Vertices.UseDoublePrecisionVertices=true;
        try
        {
            using(var input=new BinaryReader(File.OpenRead(path),Encoding.UTF8))
            {
                if(Encoding.ASCII.GetString(input.ReadBytes(8))!="QXTIN01\0")throw new IOException("Unknown mesh binary header");
                int vertices=input.ReadInt32(),faces=input.ReadInt32();
                if(vertices<3 || faces<1 || input.BaseStream.Length!=16L+vertices*24L+faces*12L)throw new IOException("Invalid or truncated mesh binary counts");
                for(int i=0;i<vertices;i++)
                {
                    double x=input.ReadDouble(),y=input.ReadDouble(),z=input.ReadDouble();
                    if(Double.IsNaN(x)||Double.IsInfinity(x)||Double.IsNaN(y)||Double.IsInfinity(y)||Double.IsNaN(z)||Double.IsInfinity(z))throw new IOException("Nonfinite mesh coordinates");
                    mesh.Vertices.Add(x,y,z);
                }
                for(int i=0;i<faces;i++)
                {
                    int a=input.ReadInt32(),b=input.ReadInt32(),c=input.ReadInt32();
                    if(a<0 || b<0 || c<0 || a>=vertices || b>=vertices || c>=vertices)throw new IOException("Mesh face index outside vertices");
                    mesh.Faces.AddFace(a,b,c);
                }
            }
            mesh.Normals.ComputeNormals();return mesh;
        }
        catch{mesh.Dispose();throw;}
    }
    static Dictionary<string,object> MeshIntegrity(Rhino.Geometry.Mesh mesh,string name,bool requireClosed)
    {
        bool oriented,hasBoundary;
        bool manifold=mesh.IsManifold(false,out oriented,out hasBoundary);
        bool valid=mesh.IsValid,closed=mesh.IsClosed;
        if(requireClosed)
        {
            if(!closed)throw new IOException("Appended role mesh is open: "+name);
            if(!valid)throw new IOException("Appended role mesh is invalid: "+name);
            if(!manifold || !oriented || hasBoundary)throw new IOException("Appended role mesh is not a closed oriented index manifold: "+name);
        }
        return new Dictionary<string,object>{{"valid",valid},{"closed",closed},{"manifold_by_actual_vertex_indices",manifold},{"oriented",oriented},{"has_boundary",hasBoundary},{"requires_closed",requireClosed}};
    }
    [MethodImpl(MethodImplOptions.NoInlining)]
    static int AppendMeshes(string configPath)
    {
        var serializer=new JavaScriptSerializer{MaxJsonLength=Int32.MaxValue};
        var job=serializer.Deserialize<WriteJob>(File.ReadAllText(configPath,Encoding.UTF8));
        if(job==null || job.schema_version!="1.0" || job.meshes==null || job.meshes.Count==0)throw new ArgumentException("Invalid append-mesh job");
        string output=Path.GetFullPath(job.output),source=String.IsNullOrEmpty(job.source)?null:Path.GetFullPath(job.source);
        if(source!=null && String.Equals(source,output,StringComparison.OrdinalIgnoreCase))throw new IOException("Output must not overwrite source 3dm");
        if(File.Exists(output))throw new IOException("Staging output must be a new path");
        string sourceHash=source==null?null:HashFile(source);var added=new List<Rhino.Geometry.Mesh>();
        var report=new Dictionary<string,object>();
        try
        {
            using(var model=source==null ? new Rhino.FileIO.File3dm() : Rhino.FileIO.File3dm.Read(source))
            {
                if(model==null)throw new IOException("Cannot read source 3dm");
                if(source==null)model.Settings.ModelUnitSystem=Rhino.UnitSystem.Meters;
                if(model.Settings.ModelUnitSystem!=Rhino.UnitSystem.Meters)throw new IOException("Source 3dm units must be metres");
                var originals=model.Objects.Where(o=>o!=null).ToArray();var originalMeshes=originals.Where(o=>o.Geometry is Rhino.Geometry.Mesh).ToArray();
                var records=new List<Dictionary<string,object>>();
                for(int index=0;index<job.meshes.Count;index++)
                {
                    var spec=job.meshes[index];var mesh=ReadBinaryMesh(spec.binary_path);added.Add(mesh);
                    var integrity=MeshIntegrity(mesh,spec.name,spec.require_closed);
                    var layer=new Rhino.DocObjects.Layer{Name=spec.layer??spec.name??"Calculation mesh"};
                    if(spec.color!=null && spec.color.Length==4)layer.Color=System.Drawing.Color.FromArgb(spec.color[3],spec.color[0],spec.color[1],spec.color[2]);
                    var existingLayer=model.AllLayers.FirstOrDefault(l=>l.Name==layer.Name);
                    if(existingLayer==null){model.AllLayers.Add(layer);existingLayer=model.AllLayers.First(l=>l.Name==layer.Name);}
                    int layerIndex=existingLayer.Index;
                    var attributes=new Rhino.DocObjects.ObjectAttributes{Name=spec.name??"Calculation mesh",LayerIndex=layerIndex};
                    if(spec.user_strings!=null)foreach(var pair in spec.user_strings)attributes.SetUserString(pair.Key,pair.Value);
                    Guid id=model.Objects.AddMesh(mesh,attributes);
                    integrity.Add("mesh_index",originalMeshes.Length+index);integrity.Add("role",spec.user_strings!=null&&spec.user_strings.ContainsKey("qx_role")?spec.user_strings["qx_role"]:null);
                    integrity.Add("object_id",id.ToString());integrity.Add("vertices",mesh.Vertices.Count);integrity.Add("faces",mesh.Faces.Count);
                    integrity.Add("double_precision_vertices",mesh.Vertices.UseDoublePrecisionVertices);integrity.Add("all_xyz_and_faces_equal",true);records.Add(integrity);
                }
                if(job.document_strings!=null)foreach(var pair in job.document_strings)model.Strings.SetString(pair.Key,pair.Value);
                if(!model.Write(output,8))throw new IOException("Cannot write appended 3dm");
                using(var saved=Rhino.FileIO.File3dm.Read(output))
                {
                    if(saved==null || saved.Objects.Count!=originals.Length+job.meshes.Count)throw new IOException("Saved document object count changed");
                    var all=saved.Objects.Where(o=>o!=null).ToArray();var meshes=all.Where(o=>o.Geometry is Rhino.Geometry.Mesh).ToArray();
                    if(meshes.Length!=originalMeshes.Length+added.Count)throw new IOException("Saved document mesh count changed");
                    for(int i=0;i<originals.Length;i++)
                    {
                        if(all[i].Id!=originals[i].Id || all[i].Geometry.ObjectType!=originals[i].Geometry.ObjectType)throw new IOException("Original document object identity changed at "+i);
                    }
                    for(int i=0;i<originalMeshes.Length;i++)ExactMesh((Rhino.Geometry.Mesh)originalMeshes[i].Geometry,(Rhino.Geometry.Mesh)meshes[i].Geometry,"Original terrain "+i);
                    for(int i=0;i<added.Count;i++)
                    {
                        var read=(Rhino.Geometry.Mesh)meshes[originalMeshes.Length+i].Geometry;ExactMesh(added[i],read,"Appended mesh "+i);
                        MeshIntegrity(read,"Saved "+job.meshes[i].name,job.meshes[i].require_closed);
                        if(job.meshes[i].user_strings!=null)foreach(var pair in job.meshes[i].user_strings)if(meshes[originalMeshes.Length+i].Attributes.GetUserString(pair.Key)!=pair.Value)throw new IOException("Saved role attribute changed: "+pair.Key);
                    }
                    if(job.document_strings!=null)foreach(var pair in job.document_strings)if(saved.Strings.GetValue(pair.Key)!=pair.Value)throw new IOException("Saved document string changed: "+pair.Key);
                }
                report["original_object_count"]=originals.Length;report["original_mesh_count"]=originalMeshes.Length;
                report["original_object_ids_preserved"]=true;report["all_original_terrain_xyz_and_faces_equal"]=true;report["meshes"]=records;
                report["required_closed_meshes_valid_closed_oriented_by_indices"]=true;
            }
            if(source!=null && HashFile(source)!=sourceHash)throw new IOException("Source 3dm changed during append");
            report["passed"]=true;report["path"]=output;report["sha256"]=HashFile(output);report["source_path"]=source;report["source_sha256"]=sourceHash;report["source_unchanged"]=true;report["engine"]="Rhino3dm.NET double Add / OpenNURBS";
            Console.WriteLine(serializer.Serialize(report));return 0;
        }
        finally{foreach(var mesh in added)mesh.Dispose();}
    }

    static int WritePrecisionControl(string path)
    {
        using(var model=new Rhino.FileIO.File3dm())
        using(var mesh=new Rhino.Geometry.Mesh())
        {
            model.Settings.ModelUnitSystem=Rhino.UnitSystem.Meters;
            mesh.Vertices.UseDoublePrecisionVertices=true;
            mesh.Vertices.Add(624500.0000123456,3481500.00004321,410.123456789);
            mesh.Vertices.Add(624501.0000123456,3481500.00004321,411.123456789);
            mesh.Vertices.Add(624500.0000123456,3481501.00004321,409.123456789);
            mesh.Faces.AddFace(2,0,1);
            model.Objects.AddMesh(mesh);
            if(!model.Write(path,8)) throw new IOException("Cannot write precision control");
            return 0;
        }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static int Read(string[] args)
    {
        using(var model=Rhino.FileIO.File3dm.Read(args[1]))
        {
            if(model==null) throw new IOException("Cannot read 3dm");
            if(model.Settings.ModelUnitSystem!=Rhino.UnitSystem.Meters)
                throw new InvalidOperationException("Terrain model units must be metres");
            var meshes=new System.Collections.Generic.List<Rhino.Geometry.Mesh>();
            foreach(var item in model.Objects)
                if(item.Geometry is Rhino.Geometry.Mesh) meshes.Add((Rhino.Geometry.Mesh)item.Geometry);
            int index=args.Length>3 ? Int32.Parse(args[3]) : -1;
            if(index<0 && meshes.Count!=1) throw new InvalidOperationException("Select a terrain mesh explicitly; mesh count="+meshes.Count);
            if(index<0) index=0;
            if(index>=meshes.Count) throw new ArgumentOutOfRangeException("mesh-index");
            var mesh=meshes[index];
            int triangles=mesh.Faces.Count;
            foreach(var f in mesh.Faces)
                if(!f.IsTriangle) throw new InvalidOperationException("Terrain must contain triangles; no implicit quad triangulation");
            string temporary=Path.GetFullPath(args[2])+".partial";
            using(var stream=new BinaryWriter(File.Create(temporary),Encoding.UTF8))
            {
                stream.Write(Encoding.ASCII.GetBytes("QXTIN01\0"));
                stream.Write(mesh.Vertices.Count); stream.Write(triangles);
                for(int i=0;i<mesh.Vertices.Count;i++)
                {
                    var p=mesh.Vertices.Point3dAt(i);
                    stream.Write(p.X); stream.Write(p.Y); stream.Write(p.Z);
                }
                foreach(var f in mesh.Faces)
                {
                    stream.Write(f.A); stream.Write(f.B); stream.Write(f.C);
                }
            }
            if(File.Exists(args[2])) File.Delete(args[2]);
            File.Move(temporary,args[2]);
            Console.WriteLine("{\"vertex_count\":"+mesh.Vertices.Count+
                ",\"triangle_count\":"+triangles+
                ",\"double_precision_vertices\":"+(mesh.Vertices.UseDoublePrecisionVertices ? "true" : "false")+
                ",\"mesh_index\":"+index+",\"units\":\"Meters\",\"engine\":\"Rhino3dm standalone\"}");
            return 0;
        }
    }
}
