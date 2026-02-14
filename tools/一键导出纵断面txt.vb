Option Explicit

' AutoCAD命令一键生成工具

' 将Excel列名转换为数字索引 (从1开始)
Function GetColumnIndexFromExcelName(colName As String) As Long
    Dim result As Long
    Dim i As Integer
    Dim char As String
    
    result = 0
    For i = 1 To Len(colName)
        char = Mid(colName, i, 1)
        result = result * 26 + (Asc(char) - Asc("A") + 1)
    Next i
    
    GetColumnIndexFromExcelName = result
End Function

' 将列索引转换为Excel列名格式
Function GetExcelColumnName(columnIndex As Long) As String
    Dim columnName As String
    Dim tempIndex As Long
    
    tempIndex = columnIndex - 1 ' 转换为0基础索引
    columnName = ""
    
    Do While tempIndex >= 0
        columnName = Chr(tempIndex Mod 26 + Asc("A")) & columnName
        tempIndex = tempIndex \ 26 - 1
    Loop
    
    GetExcelColumnName = columnName
End Function

' 处理独立线段列 (AX、AZ列，排除AY)
Sub ProcessIndividualLinesColumn(ws As Worksheet, colIndex As Long, txtFile As Object, ByRef commandCount As Long)
    Dim lastRow As Long
    Dim i As Long
    Dim cellValue As String
    
    lastRow = ws.Cells(ws.Rows.count, colIndex).End(xlUp).Row
    commandCount = 0
    
    ' 从第9行开始处理（跳过前8行标题）
    For i = 9 To lastRow
        cellValue = CStr(ws.Cells(i, colIndex).value) ' 直接使用单元格内容，不使用Trim
        
        If cellValue <> "" And cellValue <> "0" Then
            ' 独立线段列，如果是以pl开头的命令，确保行末有空格
            If Left(LCase(Trim(cellValue)), 2) = "pl" And Right(cellValue, 1) <> " " Then
                cellValue = cellValue & " "
            End If
            txtFile.WriteLine ScaleCoordinates(cellValue, True, GetExcelColumnName(colIndex), i) ' 独立线段，使用默认值添加空格，传递列名和行号
            commandCount = commandCount + 1
        End If
    Next i
End Sub

' 处理连续多段线列 (BA、BB、BC列)
Sub ProcessPolylineColumn(ws As Worksheet, colIndex As Long, txtFile As Object, ByRef commandCount As Long)
    Dim lastRow As Long
    Dim i As Long
    Dim cellValue As String
    
    lastRow = ws.Cells(ws.Rows.count, colIndex).End(xlUp).Row
    commandCount = 0
    
    ' 从第9行开始处理
    For i = 9 To lastRow
        cellValue = CStr(ws.Cells(i, colIndex).value) ' 直接使用单元格内容，不使用Trim
        
        If cellValue <> "" And cellValue <> "0" Then
            ' BA、BB、BC列是连续多段线，pl命令末尾不加空格
            txtFile.WriteLine ScaleCoordinates(cellValue, False, GetExcelColumnName(colIndex), i) ' 连续多段线，不添加空格，传递列名和行号
            commandCount = commandCount + 1
        End If
    Next i
End Sub

' 处理text命令列 (BD到BL列，排除BE、BH、BK)
Sub ProcessTextColumn(ws As Worksheet, colIndex As Long, txtFile As Object, ByRef commandCount As Long)
    Dim lastRow As Long
    Dim i As Long
    Dim cellValue As String
    Dim colName As String
    Dim specialRows As Collection
    Dim firstDataRow As Long ' 新增：记录该列第一条有效数据行
    
    lastRow = ws.Cells(ws.Rows.count, colIndex).End(xlUp).Row
    commandCount = 0
    
    ' 获取列名，用于判断是否需要调整x坐标
    colName = GetExcelColumnName(colIndex)
    
    ' 如果是BQ列，需要先获取特殊行号
    If colName = "BQ" Then
        Set specialRows = GetSpecialRowsFromBO(ws)
    End If
    
    ' 计算该列第一条有效数据行（只需一次）
    firstDataRow = 0
    For i = 9 To lastRow
        If CStr(ws.Cells(i, colIndex).value) <> "" And CStr(ws.Cells(i, colIndex).value) <> "0" Then
            firstDataRow = i
            Exit For
        End If
    Next i
    
    ' 从第9行开始处理（跳过前8行标题）
    For i = 9 To lastRow
        cellValue = CStr(ws.Cells(i, colIndex).value) ' 直接使用单元格内容，不使用Trim
        
        If cellValue <> "" And cellValue <> "0" Then
            ' 对于BG、BH、BI、BO、BP列，需要调整x坐标
            If colName = "BG" Or colName = "BH" Or colName = "BI" Or colName = "BO" Or colName = "BP" Then
                If i = firstDataRow Then
                    ' 第一行：x 坐标 +4.8
                    cellValue = AdjustXCoordinate(cellValue, 4.8)
                Else
                    ' 其他行：x 坐标 -0.6
                    cellValue = AdjustXCoordinate(cellValue, -0.6)
                End If
            End If
            
            ' 对于BQ列，需要根据BO列内容调整最后一个参数
            If colName = "BQ" Then
                cellValue = AdjustBQParameter(cellValue, i, specialRows)
            End If
            
            ' 对于pl命令的处理：BQ列等需要独立多段线，BA、BB、BC列需要连续多段线
            ' 但BA、BB、BC列由ProcessPolylineColumn处理，这里只处理其他列
            If Left(LCase(Trim(cellValue)), 2) = "pl" And Right(cellValue, 1) <> " " Then
                cellValue = cellValue & " "
            End If
            
            txtFile.WriteLine ScaleCoordinates(cellValue, True, colName, i) ' 修改：坐标缩放，传递列名和行号
            commandCount = commandCount + 1
        End If
    Next i
End Sub

' 调整text命令中的x坐标
Function AdjustXCoordinate(command As String, adjustment As Double) As String
    Dim parts() As String
    Dim coords() As String
    Dim xValue As Double
    Dim yPart As String
    Dim result As String
    
    ' 如果不是text命令，直接返回原值
    If InStr(1, command, "-text ") <> 1 Then
        AdjustXCoordinate = command
        Exit Function
    End If
    
    ' 移除"-text "前缀
    result = Mid(command, 7) ' 去掉"-text "
    
    ' 查找第一个空格，分离坐标部分和其余部分
    Dim spacePos As Integer
    spacePos = InStr(result, " ")
    
    If spacePos > 0 Then
        Dim coordPart As String
        Dim remainingPart As String
        
        coordPart = Left(result, spacePos - 1)
        remainingPart = Mid(result, spacePos)
        
        ' 分离x和y坐标（用逗号分隔）
        Dim commaPos As Integer
        commaPos = InStr(coordPart, ",")
        
        If commaPos > 0 Then
            ' 提取x坐标并调整
            On Error Resume Next
            xValue = CDbl(Left(coordPart, commaPos - 1))
            If Err.Number = 0 Then
                xValue = xValue + adjustment
                yPart = Mid(coordPart, commaPos) ' 保留y坐标部分（包括逗号）
                result = "-text " & CStr(xValue) & yPart & remainingPart
            Else
                ' 如果转换失败，返回原值
                result = command
            End If
            On Error GoTo 0
        Else
            ' 如果没有找到逗号，返回原值
            result = command
        End If
    Else
        ' 如果没有找到空格，返回原值
        result = command
    End If
    
    AdjustXCoordinate = result
End Function

' 获取BO列中需要保持120参数的特殊行号
Function GetSpecialRowsFromBO(ws As Worksheet) As Collection
    Dim specialRows As Collection
    Dim boColIndex As Long
    Dim lastRow As Long
    Dim i As Long
    Dim cellValue As String
    Dim firstDataRow As Long
    Dim lastDataRow As Long
    
    Set specialRows = New Collection
    boColIndex = GetColumnIndexFromExcelName("BO")
    lastRow = ws.Cells(ws.Rows.count, boColIndex).End(xlUp).Row
    
    Debug.Print "=== 开始分析BO列特殊行 ==="
    Debug.Print "BO列索引: " & boColIndex & ", 最后行: " & lastRow
    
    ' 找出BO列第一行和最后一行有数据的行号
    firstDataRow = 0
    lastDataRow = 0
    
    For i = 9 To lastRow
        cellValue = CStr(ws.Cells(i, boColIndex).value)
        If cellValue <> "" And cellValue <> "0" Then
            If firstDataRow = 0 Then firstDataRow = i
            lastDataRow = i
        End If
    Next i
    
    Debug.Print "第一行数据: " & firstDataRow & ", 最后行数据: " & lastDataRow
    
    ' 扫描BO列内容
    For i = 9 To lastRow
        cellValue = CStr(ws.Cells(i, boColIndex).value)
        If cellValue <> "" And cellValue <> "0" Then
            Debug.Print "行 " & i & ": " & cellValue
            
            ' 第一行和最后一行
            If i = firstDataRow Or i = lastDataRow Then
                On Error Resume Next
                specialRows.Add i
                On Error GoTo 0
                Debug.Print "  -> 添加为特殊行 (首行或末行)"
            ' 包含特定关键词的行
            ElseIf InStr(1, cellValue, "倒进") > 0 Or InStr(1, cellValue, "倒出") > 0 Or _
                   InStr(1, cellValue, "渡进") > 0 Or InStr(1, cellValue, "渡出") > 0 Or _
                   InStr(1, cellValue, "隧进") > 0 Or InStr(1, cellValue, "隧出") > 0 Then
                On Error Resume Next
                specialRows.Add i
                On Error GoTo 0
                Debug.Print "  -> 添加为特殊行 (包含关键词)"
            Else
                Debug.Print "  -> 普通行"
            End If
        End If
    Next i
    
    Debug.Print "特殊行总数: " & specialRows.count
    Debug.Print "=== BO列分析结束 ==="
    
    Set GetSpecialRowsFromBO = specialRows
End Function

' 调整BQ列中的最后一个参数
Function AdjustBQParameter(command As String, rowIndex As Long, specialRows As Collection) As String
    Dim isSpecialRow As Boolean
    Dim i As Integer
    Dim result As String
    
    ' 检查当前行是否为特殊行
    isSpecialRow = False
    If Not specialRows Is Nothing Then
        For i = 1 To specialRows.count
            If specialRows(i) = rowIndex Then
                isSpecialRow = True
                Exit For
            End If
        Next i
    End If
    
    ' 调试信息 - 输出到立即窗口
    Debug.Print "行 " & rowIndex & ": 是否特殊行=" & isSpecialRow & ", 原命令=" & command
    
    ' 如果是特殊行，保持120；否则将120改为100
    If isSpecialRow Then
        result = command ' 保持原样
        Debug.Print "  -> 保持120: " & result
    Else
        ' 更精确的字符串替换：查找最后一个逗号后的120
        If InStr(command, ",120") > 0 Then
            result = Replace(command, ",120", ",100")
            Debug.Print "  -> 改为100: " & result
        Else
            result = command ' 如果没有找到,120模式，保持原样
            Debug.Print "  -> 未找到,120模式，保持原样: " & result
        End If
    End If
    
    AdjustBQParameter = result
End Function

' 新增函数：缩放pl和-text命令中的X坐标
Function ScaleCoordinates(command As String, Optional addSpaceToPolyline As Boolean = True, Optional colName As String = "", Optional rowIndex As Long = 0) As String
    Dim tempCommand As String
    Dim coords() As String ' 在函数顶部声明
    Dim x As Double ' 统一声明x变量
    Dim originalX As String ' 保存原始x坐标字符串
    Dim decimalPlaces As Integer ' 小数位数
    tempCommand = Trim(LCase(command))

    If Left(tempCommand, 2) = "pl" Then
        ' 处理pl命令
        Dim parts() As String
        Dim result As String
        Dim i As Integer
        
        result = "pl"
        parts = Split(Mid(command, 3), " ")
        
        For i = 0 To UBound(parts)
            If Trim(parts(i)) <> "" Then
                coords = Split(parts(i), ",")
                If UBound(coords) = 1 Then
                    On Error Resume Next
                    originalX = coords(0)
                    x = CDbl(originalX)
                    
                    If Err.Number = 0 Then
                        ' 计算原始x坐标的小数位数
                        If InStr(originalX, ".") > 0 Then
                            decimalPlaces = Len(originalX) - InStr(originalX, ".")
                        Else
                            decimalPlaces = 0
                        End If
                        
                        ' 根据列名决定是否缩放x坐标
                        If colName = "BZ" Then
                            ' BZ列x坐标不除以2，保持原状
                            result = result & " " & originalX & "," & coords(1)
                        Else
                            ' 其他列x坐标除以2，保持小数位数
                            x = x / 2
                            result = result & " " & Format(x, "0." & String(decimalPlaces, "0")) & "," & coords(1)
                        End If
                    Else
                        result = result & " " & parts(i) ' 转换失败则保留原样
                    End If
                    On Error GoTo 0
                Else
                    result = result & " " & parts(i) ' 不是坐标对则保留原样
                End If
            End If
        Next i
        If addSpaceToPolyline Then
            ScaleCoordinates = result & " " ' pl命令最后需要一个空格
        Else
            ScaleCoordinates = result ' 连续多段线不需要空格
        End If
        
    ElseIf Left(tempCommand, 5) = "-text" Then
        ' 处理-text命令
        Dim textParts() As String
        Dim firstPart As String
        Dim remainingPart As String
        Dim spacePos As Integer
        
        ' 找到第一个空格，分离坐标和后面的参数
        firstPart = Mid(command, 7) ' 去掉 "-text "
        spacePos = InStr(firstPart, " ")
        
        If spacePos > 0 Then
            Dim coordPart As String
            coordPart = Trim(Left(firstPart, spacePos - 1))
            remainingPart = Mid(firstPart, spacePos)
            
            coords = Split(coordPart, ",")
            
            If UBound(coords) = 1 Then
                On Error Resume Next
                originalX = coords(0)
                x = CDbl(originalX)
                
                If Err.Number = 0 Then
                    ' 计算原始x坐标的小数位数
                    If InStr(originalX, ".") > 0 Then
                        decimalPlaces = Len(originalX) - InStr(originalX, ".")
                    Else
                        decimalPlaces = 0
                    End If
                    
                    ' 根据列名和行号决定x坐标处理方式
                    If colName = "BZ" Then
                        ' BZ列x坐标不除以2，保持原状
                        ScaleCoordinates = "-text " & originalX & "," & coords(1) & remainingPart
                    ElseIf (colName = "BO" Or colName = "BP" Or colName = "BG" Or colName = "BH" Or colName = "BI") And rowIndex > 0 Then
                        ' 检查是否为这些列的第一行数据
                        Dim ws As Worksheet
                        Set ws = ThisWorkbook.Worksheets("综合计算")
                        Dim colIndex As Long
                        colIndex = GetColumnIndexFromExcelName(colName)
                        
                        ' 找到该列第一行有数据的行号
                        Dim firstDataRow As Long
                        firstDataRow = 0
                        Dim checkRow As Long
                        For checkRow = 9 To ws.Cells(ws.Rows.count, colIndex).End(xlUp).Row
                            If CStr(ws.Cells(checkRow, colIndex).value) <> "" And CStr(ws.Cells(checkRow, colIndex).value) <> "0" Then
                                firstDataRow = checkRow
                                Exit For
                            End If
                        Next checkRow
                        
                        If rowIndex = firstDataRow Then
                             ' 第一行数据，x坐标固定为4.8
                             ScaleCoordinates = "-text 4.8," & coords(1) & remainingPart
                        Else
                            ' 其他行，x坐标除以2，保持小数位数
                            x = x / 2
                            ScaleCoordinates = "-text " & Format(x, "0." & String(decimalPlaces, "0")) & "," & coords(1) & remainingPart
                        End If
                    Else
                        ' 其他列x坐标除以2，保持小数位数
                        x = x / 2
                        ScaleCoordinates = "-text " & Format(x, "0." & String(decimalPlaces, "0")) & "," & coords(1) & remainingPart
                    End If
                Else
                    ScaleCoordinates = command ' 转换失败则返回原命令
                End If
                On Error GoTo 0
            Else
                ScaleCoordinates = command ' 坐标格式不正确
            End If
        Else
            ScaleCoordinates = command ' 找不到空格，格式不正确
        End If
    Else
        ' 如果不是pl或-text命令，直接返回原值
        ScaleCoordinates = command
    End If
End Function

' 主生成函数
Sub GenerateAutoCADScript()
    Dim ws As Worksheet
    Dim outputPath As String
    Dim txtFileName As String
    Dim totalCommands As Long
    Dim colCommands As Long
    Dim i As Long
    Dim wsParams As Worksheet
    Dim channelName As String
    Dim baseFileName As String
    
    ' 定义目标列
    Dim targetColumns As Variant
    Dim colName As String
    Dim colIndex As Long
    
    ' 新的目标列：BQ到BY优先，然后是其他列，最后是BM、BN和BO
    targetColumns = Array("BQ", "BR", "BS", "BT", "BU", "BV", "BW", "BX", "BY", "BA", "BB", "BC", "BG", "BH", "BI", "BP", "BZ", "BM", "BN", "BO")
    
    ' 获取"综合计算"工作表
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("综合计算")
    On Error GoTo 0
    
    If ws Is Nothing Then
        MsgBox "错误: 找不到工作表 '综合计算'", vbCritical
        Exit Sub
    End If
    
    ' 获取"线路参数计算"工作表以读取渠道名称
    On Error Resume Next
    Set wsParams = ThisWorkbook.Worksheets("线路参数计算")
    On Error GoTo 0
    
    If wsParams Is Nothing Then
        channelName = "未命名渠道"
        MsgBox "警告: 未找到 '线路参数计算' 工作表，将使用默认文件名。", vbExclamation
    Else
        channelName = Trim(CStr(wsParams.Range("E1").value))
        If channelName = "" Then
            channelName = "未命名渠道"
            MsgBox "警告: '线路参数计算' 工作表的E1单元格为空，将使用默认文件名。", vbExclamation
        End If
    End If
    
    ' 构造基本文件名
    baseFileName = channelName & "_一键生成上纵断面表格"

    ' 设置输出路径 (优先使用Excel文件目录, 如果失败则使用桌面)
    outputPath = ThisWorkbook.Path & "\"
    If Dir(outputPath, vbDirectory) = "" Then
        outputPath = Environ("USERPROFILE") & "\Desktop\"
    End If

    ' --- 新逻辑：查找可用的文件名并使用UTF-8编码打开文件 ---
    Dim counter As Integer
    Dim fso As Object
    Dim txtFile As Object
    
    counter = 0
    Set fso = CreateObject("Scripting.FileSystemObject")
    
    On Error Resume Next ' 启用错误处理，以捕获文件锁定等问题
    
    Do
        If counter = 0 Then
            txtFileName = outputPath & baseFileName & ".txt"
        Else
            txtFileName = outputPath & baseFileName & "_" & counter & ".txt"
        End If
        
        ' 尝试创建UTF-8编码的文本文件
        Set txtFile = fso.CreateTextFile(txtFileName, True, True) ' 第三个参数True表示Unicode编码
        
        ' 如果创建成功 (Err.Number = 0)，则退出循环
        If Err.Number = 0 Then Exit Do
        
        ' 如果失败，增加计数器并重试
        counter = counter + 1
        
        ' 防止无限循环
        If counter > 100 Then
            On Error GoTo 0 ' 恢复正常错误处理
            MsgBox "无法创建输出文件。文件可能被锁定，并且无法创建带后缀的新文件。", vbCritical
            Exit Sub
        End If
    Loop
    
    On Error GoTo ErrorHandler ' 为后续操作重新设置主错误处理器
    ' --- 新逻辑结束 ---
    
    totalCommands = 0

    ' 在写入列命令前，先写入表头多段线命令
    txtFile.WriteLine "pl 0,0 -40,0 "
    txtFile.WriteLine "pl 0,15 -40,15 "
    txtFile.WriteLine "pl 0,30 -40,30 "
    txtFile.WriteLine "pl 0,45 -40,45 "
    txtFile.WriteLine "pl 0,75 -40,75 "
    txtFile.WriteLine "pl 0,100 -40,100 "
    txtFile.WriteLine "pl 0,110 -40,110 "
    txtFile.WriteLine "pl 0,120 -40,120 "
    txtFile.WriteLine "pl -40,0 -40,120 "
    txtFile.WriteLine "" ' 空行分隔

    ' 处理所有目标列：BQ到BY优先，然后是其他列，最后是BM、BN和BO
    Debug.Print "处理目标列:"
    For i = 0 To UBound(targetColumns)
        colName = targetColumns(i)
        colIndex = GetColumnIndexFromExcelName(colName)
        
        Debug.Print "正在处理 " & colName & " 列..."
        
        ' 根据列名选择合适的处理函数
        If colName = "BA" Or colName = "BB" Or colName = "BC" Then
            ' BA、BB、BC列是连续多段线，使用ProcessPolylineColumn处理
            ProcessPolylineColumn ws, colIndex, txtFile, colCommands
        Else
            ' 其他列使用ProcessTextColumn处理
            ProcessTextColumn ws, colIndex, txtFile, colCommands
        End If
        
        totalCommands = totalCommands + colCommands
        Debug.Print "  写入了 " & colCommands & " 个命令"
        
        ' 在每列之间添加空格（AutoCAD命令结束用语）
        If i < UBound(targetColumns) Then
            txtFile.WriteLine ""
        End If
    Next i
    
    ' 关闭文件
    txtFile.Close
    Set txtFile = Nothing
    Set fso = Nothing

    ' 询问用户是否要打开文件
    Dim userChoice As VbMsgBoxResult
    userChoice = MsgBox("AutoCAD命令文本文件生成成功!" & vbCrLf & vbCrLf & _
                       "文件已保存至: " & txtFileName & vbCrLf & vbCrLf & _
                       "请用word/wps/记事本打开，复制全部内容后，在AutoCAD的命令行中粘贴。" & vbCrLf & vbCrLf & _
                       "是否现在打开文件？", _
                       vbYesNo + vbQuestion, "生成完成")

    ' 如果用户选择"是"，则打开文件
    If userChoice = vbYes Then
        On Error Resume Next
        ' 使用默认的Office程序或WPS打开文件
        CreateObject("Shell.Application").ShellExecute txtFileName
        If Err.Number <> 0 Then
            ' 如果失败，尝试使用WScript.Shell方法
            Err.Clear
            CreateObject("WScript.Shell").Run """" & txtFileName & """"
            If Err.Number <> 0 Then
                MsgBox "无法自动打开文件，请手动打开：" & vbCrLf & txtFileName, vbExclamation
            End If
        End If
        On Error GoTo ErrorHandler
    End If

    Exit Sub
    
ErrorHandler:
    If Not txtFile Is Nothing Then
        txtFile.Close
        Set txtFile = Nothing
    End If
    If Not fso Is Nothing Then Set fso = Nothing
    
    MsgBox "生成文件时发生意外错误: " & Err.Description & vbCrLf & vbCrLf & _
           "错误代码: " & Err.Number, vbCritical, "文件生成错误"

End Sub

' 预览命令内容
Sub PreviewCommands()
    Dim ws As Worksheet
    Dim targetColumns As Variant
    Dim colName As String
    Dim colIndex As Long
    Dim i As Long
    Dim j As Long
    Dim cellValue As String
    Dim previewCount As Integer
    Dim lastRow As Long
    Dim header As String
    
    previewCount = 3
    ' 新的目标列：BQ到BY优先，然后是其他列，最后是BM、BN和BO
    targetColumns = Array("BQ", "BR", "BS", "BT", "BU", "BV", "BW", "BX", "BY", "BA", "BB", "BC", "BG", "BH", "BI", "BP", "BZ", "BM", "BN", "BO")
    
    ' 获取"综合计算"工作表
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("综合计算")
    On Error GoTo 0
    
    If ws Is Nothing Then
        MsgBox "错误: 找不到工作表 '综合计算'", vbCritical
        Exit Sub
    End If
    
    Debug.Print "=" & String(60, "=")
    Debug.Print "AutoCAD命令预览 (前" & previewCount & "个命令)"
    Debug.Print "=" & String(60, "=")
    
    ' 预览目标列 (BQ到BY优先，然后是其他列，最后是BM、BN和BO)
    Debug.Print ""
    Debug.Print "目标列 (BQ到BY优先，然后是其他列，最后是BM、BN和BO):"
    For i = 0 To UBound(targetColumns)
        colName = targetColumns(i)
        colIndex = GetColumnIndexFromExcelName(colName)
        
        header = CStr(ws.Cells(1, colIndex).value)
        Debug.Print "  " & colName & " 列 (" & header & "):"
        
        lastRow = ws.Cells(ws.Rows.count, colIndex).End(xlUp).Row
        Dim count As Integer
        count = 0
        
        For j = 9 To lastRow
            If count >= previewCount Then Exit For
            cellValue = CStr(ws.Cells(j, colIndex).value)
            If cellValue <> "" And cellValue <> "0" Then
                Debug.Print "    " & (count + 1) & ". " & cellValue
                count = count + 1
            End If
        Next j
        
        If count = 0 Then
            Debug.Print "    该列无有效命令"
        End If
        Debug.Print ""
    Next i
    
    Debug.Print "=" & String(60, "=")
End Sub

' 一键执行：预览 + 生成
Sub OneClickGenerate()
    PreviewCommands
    GenerateAutoCADScript
End Sub
















