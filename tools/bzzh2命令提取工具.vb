Option Explicit

' bzzh2命令提取工具
' 从"IP点上平面图"工作表中提取CDE三列数据并保存为ANSI格式txt文件

' 主函数：bzzh2命令的提取
Sub bzzh2命令的提取()
    Dim ws As Worksheet
    Dim outputPath As String
    Dim baseFileName As String
    Dim txtFileName As String
    Dim lastRow As Long
    Dim i As Long
    Dim cValue As String, dValue As String, eValue As String
    Dim dataCount As Long
    Dim fso As Object
    Dim txtFile As Object
    Dim counter As Integer
    Dim response As VbMsgBoxResult
    
    ' 错误处理
    On Error GoTo ErrorHandler
    
    ' 获取"IP点上平面图"工作表
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("IP点上平面图")
    On Error GoTo 0
    
    If ws Is Nothing Then
        MsgBox "错误: 找不到工作表 'IP点上平面图'" & vbCrLf & vbCrLf & _
               "请确保工作簿中存在名为'IP点上平面图'的工作表。", _
               vbCritical, "工作表不存在"
        Exit Sub
    End If
    
    ' 检查数据范围
    lastRow = GetLastRowWithData(ws)
    
    If lastRow < 3 Then
        MsgBox "错误: 工作表中没有足够的数据" & vbCrLf & vbCrLf & _
               "需要至少从第3行开始有数据。", _
               vbExclamation, "数据不足"
        Exit Sub
    End If
    
    ' 验证CDE列是否有数据
    If Not ValidateDataExists(ws, lastRow) Then
        MsgBox "警告: CDE列中没有发现有效数据" & vbCrLf & vbCrLf & _
               "请检查工作表中第3行及以后的CDE列是否包含数据。", _
               vbExclamation, "无有效数据"
        Exit Sub
    End If
    
    ' 设置输出路径（与工作簿同一文件夹）
    outputPath = ThisWorkbook.Path & "\"
    If Dir(outputPath, vbDirectory) = "" Then
        outputPath = Environ("USERPROFILE") & "\Desktop\"
        MsgBox "注意: 工作簿路径不可用，文件将保存到桌面。", vbInformation
    End If
    
    ' 构造基本文件名
    baseFileName = "IP点上平面图_CDE数据_bzzh2"
    
    ' 查找可用的文件名
    counter = 0
    Set fso = CreateObject("Scripting.FileSystemObject")
    
    Do
        If counter = 0 Then
            txtFileName = outputPath & baseFileName & ".txt"
        Else
            txtFileName = outputPath & baseFileName & "_" & counter & ".txt"
        End If
        
        ' 检查文件是否存在
        If Not fso.FileExists(txtFileName) Then Exit Do
        
        counter = counter + 1
        
        ' 防止无限循环
        If counter > 100 Then
            MsgBox "错误: 无法创建唯一的文件名" & vbCrLf & vbCrLf & _
                   "目录中可能存在太多同名文件。", _
                   vbCritical, "文件创建失败"
            Exit Sub
        End If
    Loop
    
    ' 创建ANSI格式的文本文件
    On Error Resume Next
    Set txtFile = fso.CreateTextFile(txtFileName, True, False) ' False表示ANSI编码
    On Error GoTo 0
    
    If txtFile Is Nothing Then
        MsgBox "错误: 无法创建输出文件" & vbCrLf & vbCrLf & _
               "请检查文件路径权限或文件是否被其他程序占用。", _
               vbCritical, "文件创建失败"
        Exit Sub
    End If
    
    ' 写入文件头部信息
    txtFile.WriteLine "' bzzh2命令数据文件"
    txtFile.WriteLine "' 生成时间: " & Format(Now, "yyyy-mm-dd hh:mm:ss")
    txtFile.WriteLine "' 数据来源: " & ws.Name & " 工作表 CDE列"
    txtFile.WriteLine "' 数据范围: 第3行至第" & lastRow & "行"
    txtFile.WriteLine "' =========================================="
    txtFile.WriteLine ""
    
    ' 提取并写入CDE列数据
    dataCount = 0
    For i = 3 To lastRow
        cValue = Trim(CStr(ws.Cells(i, 3).value)) ' C列
        dValue = Trim(CStr(ws.Cells(i, 4).value)) ' D列
        eValue = Trim(CStr(ws.Cells(i, 5).value)) ' E列
        
        ' 检查是否有任何一列有数据
        If cValue <> "" Or dValue <> "" Or eValue <> "" Then
            ' 写入数据，使用制表符分隔
            txtFile.WriteLine cValue & vbTab & dValue & vbTab & eValue
            dataCount = dataCount + 1
        End If
    Next i
    
    ' 写入文件尾部信息
    txtFile.WriteLine ""
    txtFile.WriteLine "' =========================================="
    txtFile.WriteLine "' 总计导出数据行数: " & dataCount
    
    ' 关闭文件
    txtFile.Close
    Set txtFile = Nothing
    Set fso = Nothing
    
    ' 显示成功消息和操作选项
    response = MsgBox("bzzh2命令数据提取成功！" & vbCrLf & vbCrLf & _
                     "文件保存路径: " & txtFileName & vbCrLf & vbCrLf & _
                     "导出数据行数: " & dataCount & vbCrLf & vbCrLf & _
                     "请使用ZDM的bzzh2命令完成建筑物进出口上平面图。" & vbCrLf & vbCrLf & _
                     "是否要立即打开该txt文件？", _
                     vbInformation + vbYesNo, "提取完成")
    
    ' 如果用户选择是，则打开文件
    If response = vbYes Then
        OpenTextFile txtFileName
    End If
    
    Exit Sub
    
ErrorHandler:
    ' 清理资源
    If Not txtFile Is Nothing Then
        txtFile.Close
        Set txtFile = Nothing
    End If
    If Not fso Is Nothing Then Set fso = Nothing
    
    MsgBox "提取过程中发生错误: " & Err.Description & vbCrLf & vbCrLf & _
           "错误代码: " & Err.Number, _
           vbCritical, "提取失败"
End Sub

' 辅助函数：获取包含数据的最后一行
Private Function GetLastRowWithData(ws As Worksheet) As Long
    Dim lastRowC As Long, lastRowD As Long, lastRowE As Long
    
    ' 分别获取CDE列的最后一行
    lastRowC = ws.Cells(ws.Rows.count, 3).End(xlUp).Row ' C列
    lastRowD = ws.Cells(ws.Rows.count, 4).End(xlUp).Row ' D列
    lastRowE = ws.Cells(ws.Rows.count, 5).End(xlUp).Row ' E列
    
    ' 返回最大值
    GetLastRowWithData = Application.Max(lastRowC, lastRowD, lastRowE)
End Function

' 辅助函数：验证CDE列是否有有效数据
Private Function ValidateDataExists(ws As Worksheet, lastRow As Long) As Boolean
    Dim i As Long
    Dim cValue As String, dValue As String, eValue As String
    
    ValidateDataExists = False
    
    ' 从第3行开始检查
    For i = 3 To lastRow
        cValue = Trim(CStr(ws.Cells(i, 3).value))
        dValue = Trim(CStr(ws.Cells(i, 4).value))
        eValue = Trim(CStr(ws.Cells(i, 5).value))
        
        ' 如果任何一列有数据，则认为有有效数据
        If cValue <> "" Or dValue <> "" Or eValue <> "" Then
            ValidateDataExists = True
            Exit Function
        End If
    Next i
End Function

' 辅助函数：打开文本文件
Private Sub OpenTextFile(filePath As String)
    On Error GoTo OpenError
    
    ' 使用默认程序打开文件
    Shell "notepad.exe """ & filePath & """", vbNormalFocus
    Exit Sub
    
OpenError:
    ' 如果notepad失败，尝试使用Shell Execute
    On Error GoTo OpenError2
    Shell "cmd /c start """" """ & filePath & """", vbHide
    Exit Sub
    
OpenError2:
    MsgBox "无法自动打开文件，请手动打开以下文件：" & vbCrLf & vbCrLf & _
           filePath, vbInformation, "打开文件"
End Sub

' 预览功能：查看将要提取的数据
Sub 预览bzzh2数据()
    Dim ws As Worksheet
    Dim lastRow As Long
    Dim i As Long
    Dim cValue As String, dValue As String, eValue As String
    Dim previewData As String
    Dim dataCount As Long
    Dim previewLimit As Long
    
    previewLimit = 10 ' 预览前10行数据
    
    ' 获取工作表
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("IP点上平面图")
    On Error GoTo 0
    
    If ws Is Nothing Then
        MsgBox "错误: 找不到工作表 'IP点上平面图'", vbCritical
        Exit Sub
    End If
    
    lastRow = GetLastRowWithData(ws)
    
    If lastRow < 3 Then
        MsgBox "工作表中没有足够的数据进行预览。", vbExclamation
        Exit Sub
    End If
    
    previewData = "数据预览 (前" & previewLimit & "行):" & vbCrLf & _
                  String(50, "=") & vbCrLf & _
                  "行号" & vbTab & "C列" & vbTab & "D列" & vbTab & "E列" & vbCrLf & _
                  String(50, "-") & vbCrLf
    
    dataCount = 0
    For i = 3 To lastRow
        If dataCount >= previewLimit Then Exit For
        
        cValue = Trim(CStr(ws.Cells(i, 3).value))
        dValue = Trim(CStr(ws.Cells(i, 4).value))
        eValue = Trim(CStr(ws.Cells(i, 5).value))
        
        If cValue <> "" Or dValue <> "" Or eValue <> "" Then
            previewData = previewData & i & vbTab & cValue & vbTab & dValue & vbTab & eValue & vbCrLf
            dataCount = dataCount + 1
        End If
    Next i
    
    previewData = previewData & String(50, "=") & vbCrLf & _
                  "总数据行范围: 第3行至第" & lastRow & "行" & vbCrLf & _
                  "预览显示的有效数据行数: " & dataCount
    
    MsgBox previewData, vbInformation, "数据预览"
End Sub

