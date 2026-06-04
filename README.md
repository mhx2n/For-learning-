# 🤖 Facebook → Telegram Bot

Facebook Page থেকে সুন্দর বাংলা স্ট্যাটাস সংগ্রহ করে Telegram চ্যানেলে পোস্ট করে।

---

## ✨ ফিচার সমূহ

- 📥 একাধিক Facebook Page থেকে পোস্ট সংগ্রহ
- 👀 Admin/Owner-এর inbox-এ approval request
- ✅ এক ক্লিকে অনুমোদন বা বাতিল
- ✏️ পোস্ট সম্পাদনা করার সুবিধা
- 🎨 সুন্দর ফরম্যাটে চ্যানেলে পোস্ট
- 📊 Bandwidth monitor (৫ GB সীমা)
- 🌐 Render Free-তে deploy উপযোগী

---

## 🚀 Render-এ Deploy করার ধাপ

### ধাপ ১ — Telegram Bot তৈরি করো
1. Telegram-এ [@BotFather](https://t.me/BotFather) খোলো
2. `/newbot` পাঠাও
3. নাম দাও → Bot Token পাবে (সংরক্ষণ করো)

### ধাপ ২ — তোমার Telegram ID নাও
1. [@userinfobot](https://t.me/userinfobot) খোলো
2. `/start` পাঠাও → তোমার ID পাবে

### ধাপ ৩ — Channel তৈরি করো
1. Telegram-এ নতুন Channel তৈরি করো
2. বটকে Channel-এর Admin করো
3. Channel username নোট করো (যেমন: `@my_bangla_status`)

### ধাপ ৪ — GitHub-এ Upload করো
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/তোমার-নাম/fb-telegram-bot.git
git push -u origin main
```

### ধাপ ৫ — Render-এ Deploy করো
1. [render.com](https://render.com) → Sign up (GitHub দিয়ে)
2. **New** → **Web Service** → তোমার repo বেছে নাও
3. নিচের Environment Variables দাও:

| Variable | মান |
|----------|-----|
| `BOT_TOKEN` | BotFather থেকে পাওয়া token |
| `CHANNEL_ID` | `@channelname` বা `-100xxxxx` |
| `OWNER_IDS` | তোমার Telegram ID |
| `ADMIN_IDS` | Admin-দের ID (কমা দিয়ে) |
| `WEBHOOK_URL` | `https://তোমার-app.onrender.com` |
| `FETCH_INTERVAL_MINUTES` | `30` |

4. **Deploy** বাটন চাপো!

---

## 📱 বট ব্যবহার

### Facebook Page যোগ করো
```
/addpage https://facebook.com/pagename
/addpage pagename
```

### সব Page দেখো
```
/listpages
```

### Page সরাও
```
/removepage 1
```

### Pending পোস্ট দেখো
```
/pending
```

### এখনই পোস্ট আনো
```
/fetch
```

### পরিসংখ্যান দেখো
```
/stats
```

---

## 📋 Approval Flow

```
Facebook Page → Bot Fetch → Owner/Admin Inbox
                                    ↓
                          [✅ অনুমোদন] [❌ বাতিল] [✏️ সম্পাদনা]
                                    ↓
                              Telegram Channel
```

---

## 🌐 Health Check

Render-এর জন্য এই endpoint-গুলো উপলব্ধ:
- `GET /health` → `{"status": "ok", ...}`
- `GET /ping` → একই
- `GET /status` → বিস্তারিত

---

## ⚠️ গুরুত্বপূর্ণ নোট

- **Facebook scraping** মাঝে মাঝে কাজ না-ও করতে পারে (Facebook block করতে পারে)
- **Bandwidth** প্রতি fetch-এ ~50-200 KB ব্যবহার হয়। ৩০ মিনিট পরপর fetch = দিনে ~২৪৪ MB
- **Render Free** tier-এ মাসে ৭৫০ ঘণ্টা runtime পাবে (একটি service-এর জন্য যথেষ্ট)
- বট `.db` ফাইলে data সংরক্ষণ করে — Render-এ restart হলে data যাবে। Persistent রাখতে **Render Disk** যোগ করো।

---

## 🛠️ Local Test

```bash
pip install -r requirements.txt

# .env ফাইল তৈরি করো
cp .env.example .env
# .env সম্পাদনা করো

# চালাও
python main.py
```
