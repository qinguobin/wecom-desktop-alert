' WeCom Desktop Alert - silent watchdog launcher (runs at Windows logon)
Option Explicit
Dim fso, ws, home, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
home = "D:\WeComDesktopAlert"

If fso.FileExists("D:\Python312\pythonw.exe") Then
  py = "D:\Python312\pythonw.exe"
ElseIf fso.FileExists(home & "\.venv\Scripts\pythonw.exe") Then
  py = home & "\.venv\Scripts\pythonw.exe"
Else
  py = "pythonw"
End If

ws.CurrentDirectory = home
ws.Run """" & py & """ """ & home & "\watchdog.py""", 0, False
