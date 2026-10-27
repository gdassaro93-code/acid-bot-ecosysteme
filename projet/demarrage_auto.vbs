' 04/10 — lanceur INVISIBLE de la reprise apres crash.
' Le patron : «…
' …». Une tache planifiee qui appelle un .bat fait clignoter une
' console, meme en mode minimise. Ce script le lance avec le parametre 0
' = fenetre cachee : rien n'apparait jamais a l'ecran.
' Le .bat appele verifie lui-meme le temoin ecosysteme_actif.flag et ne
' fait RIEN s'il est absent.
Set s = CreateObject("WScript.Shell")
d = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
s.CurrentDirectory = d
s.Run "cmd /c """ & d & "DEMARRAGE_AUTO.bat""", 0, False
