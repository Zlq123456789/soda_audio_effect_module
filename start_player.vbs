Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = currentDir
ws.Run "pythonw.exe """ & currentDir & "\soda_player_gui_qt.py""", 1, False
