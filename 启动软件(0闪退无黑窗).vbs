Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = "C:\code2\soda_audio_effect_module"
ws.Run "pythonw.exe ""C:\code2\soda_audio_effect_module\soda_player_gui_qt.py""", 0, False
