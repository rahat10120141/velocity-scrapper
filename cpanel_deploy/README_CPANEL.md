# ⚡ VELOCITY SCALPER: cPanel সার্ভারে লাইভ ডিপ্লয়মেন্ট গাইড (সম্পূর্ণ নির্দেশিকা)

এই নির্দেশিকাটি অনুসরণ করে আপনি খুব সহজেই **cPanel Shared Hosting** বা **cPanel VPS**-এ **Velocity Scalper (Donchian Tri-Engine)** ডিপ্লয় করতে পারবেন। cPanel-এর নেটিভ **"Setup Python App"** (CloudLinux Phusion Passenger) ব্যবহার করে ওয়েব ড্যাশবোর্ড এবং ২৪/৭ অটোমেটেড ট্রেডিং ইঞ্জিন চালু করার প্রতিটি ধাপ নিচে দেওয়া হলো।

---

## 📁 এই ফোল্ডারের ফাইল পরিচিতি

এই `cpanel_deploy` প্যাকেজটি সম্পূর্ণ স্বয়ংসম্পূর্ণ। এর ভেতর অপ্রয়োজনীয় ব্যাকটেস্ট বা টেস্টিং ফাইল নেই, শুধুমাত্র লাইভ সার্ভারে চালানোর জন্য প্রয়োজনীয় ফাইলগুলো সাজানো রয়েছে:

| ফাইল / ফোল্ডার | ভূমিকা |
| :--- | :--- |
| `passenger_wsgi.py` | cPanel Phusion Passenger-এর প্রধান এন্ট্রি পয়েন্ট। এটি FastAPI-কে WSGI-তে ব্রিজ করে এবং ড্যাশবোর্ড ও ইঞ্জিন অটো-স্টার্ট করে। |
| `app.py` | FastAPI অ্যাপ্লিকেশন এবং রিয়েল-টাইম ড্যাশবোর্ড REST API। |
| `engine.py` | ৩টি কোয়ান্ট ইঞ্জিন (Ladder, Trailing, Runner)-এর এক্সিকিউশন কোর ও প্রসেস ফাইল-লক। |
| `strategy.py` | ২০-ঘণ্টার ডনচিয়ান চ্যানেল ব্রেকআউট + ২০০ EMA ট্রেন্ড শিল্ড স্ট্র্যাটেজি। |
| `config.py` | ৩টি স্লট, লিভারেজ, মার্জিন ও রিস্ক কনফিগারেশন। |
| `binance_client.py` | হাই-স্পিড Binance Futures / Spot REST API ক্লায়েন্ট। |
| `indicators.py` | ভেক্টরাইজড টেকনিক্যাল ইন্ডিকেটর ক্যালকুলেশন। |
| `data_recorder.py` | ট্রেড ট্র্যাজেক্টরি ও জার্নি লগার। |
| `run_daemon.py` | ব্যাকগ্রাউন্ড ক্রন জব বা টার্মিনালের জন্য স্ট্যান্ডঅ্যালোন স্ক্যানার। |
| `requirements.txt` | প্রোডাকশন ডিপেনডেন্সি তালিকা (FastAPI, pandas, numpy, uvicorn, a2wsgi ইত্যাদি)। |
| `bot_state_*.json` | ৩টি ইঞ্জিনের প্রারম্ভিক ক্যাপিটাল স্টেট ($১০০ করে প্রতি ইঞ্জিন, মোট $৩০০ পোর্টফোলিও)। |
| `.env` ও `.env.example` | ট্রেডিং মোড (`PAPER` বা `LIVE_FUTURES`) ও Binance API কী। |
| `web/` | প্রিমিয়াম ওয়েব ড্যাশবোর্ড UI (`index.html`, `style.css`, `app.js`)। |
| `logs/` ও `data/` | সার্ভারের রানটাইম লগ ও ট্র্যাজেক্টরি ডেটা ডিরেক্টরি। |

---

## 🚀 স্টেপ-বাই-স্টেপ ডিপ্লয়মেন্ট নির্দেশিকা

### ধাপ ১: সাব-ডোমেন তৈরি করা (সুপারিশকৃত)
1. আপনার **cPanel** ড্যাশবোর্ডে লগইন করুন।
2. **Domains** &rarr; **Domains** (বা **Subdomains**) অপশনে যান।
3. একটি সাব-ডোমেন তৈরি করুন, যেমন: `scalper.yourdomain.com` (বা `bot.yourdomain.com`)।
4. এর **Document Root** হিসেবে একটি ফোল্ডার নাম দিন, যেমন: `scalper` (বা `public_html/scalper`)।

---

### ধাপ ২: ফাইল আপলোড করা
1. cPanel থেকে **File Manager** ওপেন করুন।
2. আপনার সাব-ডোমেনের ডিরেক্টরিতে যান (যেমন: `/home/USERNAME/scalper/`)।
3. আপনার কম্পিউটার থেকে **`cpanel_deploy.zip`** ফাইলটি আপলোড করুন।
4. আপলোড শেষ হলে `cpanel_deploy.zip`-এর উপর রাইট ক্লিক করে **Extract** সিলেক্ট করুন।
5. নিশ্চিত করুন যে `passenger_wsgi.py`, `app.py`, `config.py`, এবং `web` ফোল্ডার সরাসরি ডিরেক্টরির রুটেই রয়েছে (কোনো সাব-ফোল্ডারের ভেতর যেন আটকে না থাকে)।

---

### ধাপ ৩: cPanel-এ Python App তৈরি করা
1. cPanel সার্চ বারে লিখুন **"Setup Python App"** (Software সেকশনের অধীনে) এবং এটি ওপেন করুন।
2. উপরে ডানপাশে **Create Application** বাটনে ক্লিক করুন:
   * **Python version:** সিলেক্ট করুন **3.10** অথবা **3.11** (সুপারিশকৃত)।
   * **Application root:** আপনার ডিরেক্টরির নাম লিখুন (যেমন: `scalper` বা `public_html/scalper`)।
   * **Application URL:** আপনার তৈরিকৃত সাব-ডোমেনটি সিলেক্ট করুন (`scalper.yourdomain.com`)।
   * **Application startup file:** হুবহু লিখুন: `passenger_wsgi.py`
   * **Application Entry point:** হুবহু লিখুন: `application`
3. ডানদিকের উপরে **Create** বাটনে ক্লিক করুন।

---

### ধাপ ৪: রিকোয়ারমেন্টস (Dependencies) ইন্সটল করা
cPanel GUI বা Terminal — যেকোনো একটি পদ্ধতিতে ইন্সটল করতে পারেন:

#### পদ্ধতি ক: cPanel GUI দিয়ে (খুব সহজ)
1. Python App তৈরির পর পেজটি নিচের দিকে স্ক্রোল করে **Configuration files** সেকশনে যান।
2. টেক্সট বক্সে লিখুন: `requirements.txt` এবং পাশে **Add** বাটনে ক্লিক করুন।
3. এবার `requirements.txt`-এর পাশে থাকা **"Run Pip Install"** বাটনে ক্লিক করুন।
4. ১-২ মিনিট অপেক্ষা করুন (FastAPI, pandas, numpy, a2wsgi ইত্যাদি স্বয়ংক্রিয়ভাবে ইন্সটল হয়ে যাবে)।
5. ইন্সটলেশন সফল হলে পেজের একদম উপরে গিয়ে **"Restart"** বাটনে ক্লিক করুন।

#### পদ্ধতি খ: cPanel Terminal দিয়ে (যদি টার্মিনাল অ্যাক্সেস থাকে)
1. Python App পেজের একদম উপরে ভার্চুয়াল পরিবেশ সক্রিয় করার কমান্ড দেখতে পাবেন (যেমন: `source /home/USERNAME/virtualenv/scalper/3.11/bin/activate`)।
2. cPanel-এর **Terminal** ওপেন করে কমান্ডগুলো দিন:
   ```bash
   source /home/USERNAME/virtualenv/scalper/3.11/bin/activate
   cd /home/USERNAME/scalper
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

---

### ধাপ ৫: ট্রেডিং মোড ও API কী সেট করা (`.env`)
1. cPanel **File Manager**-এ যান। উপরে Settings-এ গিয়ে **"Show Hidden Files (dotfiles)"** টিক দেওয়া আছে কিনা দেখে নিন।
2. `.env` ফাইলটিতে রাইট ক্লিক করে **Edit** করুন:
   * **সিমুলেশন / পেপার ট্রেডিং করতে চাইলে:**
     ```ini
     TRADING_MODE=PAPER
     ENVIRONMENT=TESTNET
     ```
   * **আসল ব্যালেন্সে রিয়েল লাইভ ট্রেড করতে চাইলে:**
     ```ini
     TRADING_MODE=LIVE_FUTURES
     ENVIRONMENT=LIVE
     BINANCE_FUTURES_API_KEY=your_binance_api_key_here
     BINANCE_FUTURES_API_SECRET=your_binance_api_secret_here
     ```
3. ফাইলটি Save করুন এবং cPanel Python App ম্যানেজারে গিয়ে **Restart** বাটনে ক্লিক করুন।

---

### ধাপ ৬: ⚠️ সবচেয়ে গুরুত্বপূর্ণ — ২৪/৭ অটো-রানিং চালু রাখা (Cron Job)

> [!IMPORTANT]
> **কেন এই ধাপটি cPanel-এ বাধ্যতামূলক?**  
> cPanel Shared Hosting-এ যদি কোনো ভিজিটর ১৫-২০ মিনিট ওয়েবসাইটে না ঢোকে, তাহলে সার্ভার মেমরি বাঁচাতে পাইথন প্রসেসকে ঘুম পাড়িয়ে দেয় (Sleep Mode)।  
> কিন্তু ট্রেডিং বটকে প্রতি ৩-৪ সেকেন্ড পর পর প্রফিট লক ও স্টপ-লস মনিটর করতে হয়!

সার্ভার যেন কখনো বট বন্ধ না করে, সেজন্য cPanel-এ নিচের সহজ ক্রন জবটি সেট করুন:

1. cPanel থেকে **Cron Jobs** ওপেন করুন।
2. *Common Settings*-এ গিয়ে সিলেক্ট করুন **Once Per 5 Minutes (`*/5 * * * *`)** বা **Once Per Minute (`* * * * *`)**।
3. Command বক্সে লিখুন (আপনার ডোমেন নাম দিন):
   ```bash
   curl -s https://scalper.yourdomain.com/api/status > /dev/null 2>&1
   ```
4. **Add New Cron Job** বাটনে ক্লিক করুন।  
   *ফলাফল: প্রতি ১ থেকে ৫ মিনিট পর পর ক্রন জব আপনার বটকে পিং করবে, ফলে cPanel সার্ভার কখনোই বটকে স্লিপ মোডে পাঠাতে পারবে না।*

#### অতিরিক্ত ব্যাকগ্রাউন্ড গ্যারান্টি (ঐচ্ছিক কিন্তু ১০০% বুলেটপ্রুফ):
যদি আপনি চান ব্যাকগ্রাউন্ড স্ক্যানার সম্পূর্ণ আলাদাভাবে ২৪ ঘণ্টা এক সেকেন্ডও না থেমে চলুক:
```bash
pgrep -f run_daemon.py > /dev/null || /home/USERNAME/virtualenv/scalper/3.11/bin/python /home/USERNAME/scalper/run_daemon.py >> /home/USERNAME/scalper/logs/daemon.log 2>&1 &
```

---

## 🔍 কীভাবে চেক করবেন সবকিছু ঠিকঠাক চলছে কিনা

1. ব্রাউজারে আপনার সাব-ডোমেন ওপেন করুন:  
   `https://scalper.yourdomain.com`
2. সুন্দর প্রিমিয়াম ডার্ক ড্যাশবোর্ড দেখতে পাবেন।
3. ড্যাশবোর্ডের উপরে দেখতে পাবেন:
   * **Master Portfolio**: মোট ব্যালেন্স $৩০০ ($১০০ প্রতি ইঞ্জিন)।
   * **Active Engine Tabs**: `Ladder`, `Trailing`, `Runner` তিনটি ইঞ্জিনের আলাদা ট্যাব।
   * **Slot Counter**: প্রতিটি ইঞ্জিনে ৩টি করে স্লট (`0/3` বা অ্যাক্টিভ ট্রেড অনুযায়ী)।
   * **Execution Feed**: প্রতি কয়েক সেকেন্ড পর পর ৫টি কয়েনের লাইভ মার্কেট স্ক্যান পালস।

---

## 🛠️ সাধারণ সমস্যার সমাধান (Troubleshooting)

1. **ব্রাউজারে ৫00 Error দেখাচ্ছে?**
   * ফাইল ম্যানেজারে গিয়ে `stderr.log` বা `logs/server.log` ফাইলটি চেক করুন। 
   * নিশ্চিত করুন যে `requirements.txt`-এর সব প্যাকেজ সঠিকভাবে ইন্সটল হয়েছে (`a2wsgi` মিসিং থাকলে এই এরর হতে পারে)।
2. **সার্ভার থেকে Binance কানেক্ট হতে পারছে কিনা কীভাবে পরীক্ষা করবেন?**
   * cPanel Terminal-এ এই কমান্ডটি দিয়ে টেস্ট করুন:
     ```bash
     curl -I https://fapi.binance.com/fapi/v1/ping
     ```
     যদি `HTTP/2 200` আসে, তাহলে আপনার হোস্টিং প্রোভাইডার Binance ব্লক করেনি।
