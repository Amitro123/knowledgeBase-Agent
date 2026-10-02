# 🧠 KnowledgeBase Agent

מאגר ידע אישי לקישורי AI — מסונכרן אוטומטית מ-Google Sheets.

## איך זה עובד

```
Google Sheets (source of truth)
  ↓  (GitHub Action — every 30 min / manual trigger)
scripts/sync_sheets.py
  ↓
data/resources.json
  ↓
index.html (GitHub Pages) ← פרונט עם חיפוש + סינון
```

### תהליך העדכון

1. **ערוך ב-Google Sheets** — הוסף או עדכן שורות בכל טאב (כל טאב = נושא / bucket).
2. **GitHub Action** רץ כל 30 דקות (או ידנית מ-Actions tab) וסנכרן את הכל ל-`data/resources.json`.
3. **GitHub Pages** מציג את הנתונים אוטומטית.

## מבנה הגיליון (Google Sheets)

| עמודה | שדה ב-JSON | תיאור |
|-------|-----------|-------|
| Date | `created` / `added_at` | תאריך הוספה |
| Link | `url` | קישור למשאב |
| Name/Author | `title` | שם המשאב / המחבר |
| Function/Summary | `summary` | תיאור קצר |
| Category | `category` | קטגוריה (tool, tutorial, reference, news, …) |
| Review/Notes | `notes` | הערות מפורטות |

שם הטאב (למשל "RAG", "MCP", "Security") הופך לתגית על כל משאב בטאב.

## מבנה הקוד

```
├── .github/workflows/
│   └── sync-sheets.yml          ← GitHub Action (Sheets → JSON)
├── data/resources.json          ← מסד הנתונים (מנוהל אוטומטית)
├── scripts/
│   ├── sync_sheets.py           ← סקריפט סנכרון מ-Sheets
│   ├── requirements-sheets.txt  ← תלויות Python לסנכרון
│   ├── test_sync_sheets.py      ← בדיקות יחידה למיפוי
│   ├── capture.py               ← (legacy) סקריפט העשרה מ-Obsidian
│   └── requirements.txt         ← (legacy) תלויות ל-capture.py
├── inbox/_TEMPLATE.md           ← (legacy) תבנית לפתקי Hermes
└── index.html                   ← פרונט (GitHub Pages)
```

## Setup — הגדרת הסנכרון

### 1. יצירת Service Account ב-Google Cloud

1. היכנס ל-[Google Cloud Console](https://console.cloud.google.com/).
2. צור פרויקט חדש (או השתמש בקיים).
3. הפעל את **Google Sheets API** (APIs & Services → Enable APIs).
4. צור Service Account (IAM & Admin → Service Accounts → Create).
5. צור מפתח JSON (Keys → Add Key → JSON) — הורד את הקובץ.

### 2. שיתוף הגיליון עם ה-Service Account

פתח את [הגיליון](https://docs.google.com/spreadsheets/d/1wWktmD3QEHIlV9ct_NH_i0UQ5ceyxMrMTTidihBmoSU/edit)
ושתף אותו (Share) עם כתובת המייל של ה-Service Account (למשל
`my-sa@my-project.iam.gserviceaccount.com`) — הרשאת **Viewer** מספיקה.

### 3. הוספת Secret ל-GitHub

1. בריפו → Settings → Secrets and variables → Actions → New repository secret.
2. שם: `GOOGLE_SERVICE_ACCOUNT_JSON`
3. ערך: הדביקו את **כל תוכן** קובץ ה-JSON של ה-Service Account.

### 4. הרצה ידנית (אופציונלי)

בכרטיסיית Actions → "Sync Google Sheets → resources.json" → Run workflow.

## הרצה מקומית

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON='{ ... }'
pip install -r scripts/requirements-sheets.txt
python scripts/sync_sheets.py
```

## בדיקות

```bash
pip install pytest
pytest scripts/test_sync_sheets.py -v
```

## Secrets נדרשים

| Secret | תיאור |
|--------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | מפתח Service Account JSON לקריאת הגיליון |

## GitHub Pages

הפרונט זמין בכתובת: `https://amitro123.github.io/knowledgeBase-Agent/`

## תצוגת גרף (Graph View)

בנוסף לתצוגת הכרטיסים הקיימת, ניתן לעבור ל**תצוגת גרף** דרך כפתור **🕸️ גרף** בסרגל הבקרה.

הגרף מציג את הקשרים בין שלושה סוגי צמתים:
- **משאב** (סגול, עיגול) — כל ערך מ-`resources.json`
- **תגית** (כחול, עיגול קטן) — מתוך מערך `tags` של כל משאב
- **קטגוריה** (ירוק, מעוין) — מתוך שדה `category`

**אינטראקציה:**
- **לחיצה** על צומת → הדגשת שכנים + פאנל פרטים (סיכום, תגיות, קישור)
- **לחיצה כפולה** על משאב → פתיחת הקישור בלשונית חדשה
- **חיפוש/סינון** עובדים גם בתצוגת הגרף (צמתים לא רלוונטיים מעומעמים)
- **גרירה + זום** נתמכים (כולל מובייל)

הגרף נבנה מ-`data/resources.json` בצד הלקוח בלבד, ללא שינוי בצינור Google Sheets → Action → JSON.

---

<details>
<summary>Legacy: Hermes / Obsidian capture path</summary>

The original flow used Obsidian/Hermes to write markdown notes into
`inbox/`, then `scripts/capture.py` enriched them with Claude (via
OpenRouter) and appended to `data/resources.json`.

This path is still present in the repo (`scripts/capture.py`,
`scripts/requirements.txt`, `inbox/_TEMPLATE.md`) but is no longer the
primary data source.  Google Sheets is now the source of truth.

### Legacy Secrets (only needed for Obsidian capture)

| Secret | תיאור |
|--------|-------|
| `OPENROUTER_API_KEY` | מפתח OpenRouter |
| `VAULT_READ_TOKEN` | GitHub PAT לקריאה מ-obsidian-vault (private) |

</details>
