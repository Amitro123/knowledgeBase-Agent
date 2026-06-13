# 🧠 KnowledgeBase Agent

מאגר ידע אישי לקישורי AI — מועשר אוטומטית בעזרת Claude דרך OpenRouter.

## איך זה עובד

```
Hermes (סוכן Obsidian) → כותב פתקי markdown ל-Shared/AmitRobot/
        ↓
GitHub Action (כל 15 דק') → קורא את הפתקים, מעשיר עם Claude
        ↓
data/resources.json ← מסד הנתונים
        ↓
index.html (GitHub Pages) ← פרונט עם חיפוש + סינון
```

## מבנה הקוד

```
├── .github/workflows/capture.yml   ← GitHub Action
├── data/resources.json             ← מסד הנתונים (מנוהל אוטומטית)
├── scripts/
│   ├── capture.py                  ← סקריפט העשרה
│   └── requirements.txt
├── inbox/_TEMPLATE.md              ← תבנית לפתקי Hermes
└── index.html                      ← פרונט (GitHub Pages)
```

## Secrets נדרשים

| Secret | תיאור |
|--------|-------|
| `OPENROUTER_API_KEY` | מפתח OpenRouter |
| `VAULT_READ_TOKEN` | GitHub PAT לקריאה מ-obsidian-vault (private) |

## פורמט פתק בתיקיית הקליטה

```yaml
---
title: "שם המשאב"
source: "https://example.com"
tags: [ai, tool]
created: 2026-01-01
---
```

## GitHub Pages

הפרונט זמין בכתובת: `https://amitro123.github.io/knowledgeBase-Agent/`
