# Josefs Vokabeltrainer – Online stellen (Railway.app)

## Schritt 1 – GitHub Repository erstellen
1. Gehe zu https://github.com → Account erstellen oder einloggen
2. Klicke **"New repository"**
3. Name: `josef-vokabeltrainer` → **Create repository**
4. Kopiere die angezeigte URL (z.B. `https://github.com/DEIN-NAME/josef-vokabeltrainer.git`)

## Schritt 2 – Code auf GitHub hochladen
Öffne die **Eingabeaufforderung** (cmd) im Ordner `JosefVokabeltrainer`:
```
cd C:\Users\Christoph\Desktop\JosefVokabeltrainer
git remote add origin https://github.com/DEIN-NAME/josef-vokabeltrainer.git
git push -u origin master
```

## Schritt 3 – Railway.app einrichten
1. Gehe zu https://railway.app → **"Start a New Project"**
2. Wähle **"Deploy from GitHub repo"**
3. Verbinde dein GitHub-Konto und wähle `josef-vokabeltrainer`
4. Railway erkennt Python/Flask automatisch

## Schritt 4 – Datenspeicher hinzufügen
Im Railway-Dashboard:
1. Klicke auf deinen Service → **"Add Volume"**
2. Mount Path: `/var/data`
3. Im Tab **"Variables"** hinzufügen:
   - Key: `DATA_DIR`  Value: `/var/data`

## Schritt 5 – App ist online!
Railway gibt dir eine URL wie:  
`https://josef-vokabeltrainer-production.up.railway.app`

Diese URL funktioniert auf jedem Gerät – PC, iPhone, iPad – von überall.

---

## Lokaler Betrieb (weiterhin möglich)
Die App läuft weiterhin lokal über `run.bat`.
Lokal gespeicherte Vokabeln und Online-Vokabeln sind getrennt.

## Kosten
Railway: $5 Gratis-Guthaben pro Monat (reicht für Josef's App)
Danach: ca. $3–5/Monat je nach Nutzung
