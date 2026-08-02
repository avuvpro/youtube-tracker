from datetime import datetime, timezone, timedelta
import json
import os
import re
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DATA_FILE = "data.json"

MONTHS_UA = {
    1: "січня",
    2: "лютого",
    3: "березня",
    4: "квітня",
    5: "травня",
    6: "червня",
    7: "липня",
    8: "серпня",
    9: "вересня",
    10: "жовтня",
    11: "листопада",
    12: "грудня",
}


def send_telegram(text):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    return None
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
  try:
    res = requests.post(url, json=payload).json()
    if res.get("ok"):
      return res["result"]["message_id"]
  except Exception as e:
    print(f"Помилка відправки в Telegram: {e}")
  return None


def edit_telegram_message(message_id, text):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
  payload = {
      "chat_id": TELEGRAM_CHAT_ID,
      "message_id": message_id,
      "text": text,
      "parse_mode": "Markdown",
  }
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Помилка редагування в Telegram: {e}")


def delete_telegram_message(message_id):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not message_id:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id}
  try:
    requests.post(url, json=payload)
    print(f"🗑 Видалено застаріле повідомлення з Telegram (ID: {message_id})")
  except Exception as e:
    print(f"Помилка видалення повідомлення в Telegram: {e}")


def get_channel_id_by_url(url):
  clean_url = url.split("?")[0]
  handle = clean_url.strip("/").split("@")[-1].rstrip(".")

  search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&q={handle}&maxResults=1&key={YOUTUBE_API_KEY}"
  try:
    res = requests.get(search_url).json()
    items = res.get("items", [])
    if items:
      ch_id = items[0]["snippet"]["channelId"]
      api_url = f"https://www.googleapis.com/youtube/v3/channels?part=contentDetails,snippet&id={ch_id}&key={YOUTUBE_API_KEY}"
      channel_res = requests.get(api_url).json()
      channel_items = channel_res.get("items", [])
      if channel_items:
        return (
            ch_id,
            channel_items[0]["contentDetails"]["relatedPlaylists"]["uploads"],
        )
  except Exception as e:
    print(f"Помилка пошуку каналу {handle} через API: {e}")

  return None, None


def parse_iso8601_duration(duration_str):
  match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
  if not match:
    return 0
  hours = int(match.group(1)) if match.group(1) else 0
  minutes = int(match.group(2)) if match.group(2) else 0
  seconds = int(match.group(3)) if match.group(3) else 0
  return hours * 3600 + minutes * 60 + seconds


def format_time_info(published_at_str):
  try:
    pub_time = datetime.fromisoformat(
        published_at_str.replace("Z", "+00:00")
    )
  except Exception:
    return published_at_str, ""

  now = datetime.now(timezone.utc)

  day = pub_time.day
  month_name = MONTHS_UA.get(pub_time.month, "")
  time_str = pub_time.strftime("%H:%M")
  formatted_date = f"{day} {month_name}, {time_str}"

  diff = now - pub_time
  total_hours = int(diff.total_seconds() // 3600)
  if total_hours < 0:
    total_hours = 0

  if total_hours < 24:
    if total_hours == 1:
      relative_str = "1 годину тому"
    elif 2 <= total_hours <= 4:
      relative_str = f"{total_hours} години тому"
    else:
      relative_str = f"{total_hours} годин тому"
  else:
    days = total_hours // 24
    if days == 1:
      relative_str = "1 день тому"
    elif 2 <= days <= 4:
      relative_str = f"{days} дні тому"
    else:
      relative_str = f"{days} днів тому"

  return formatted_date, relative_str


def get_video_stats(playlist_id):
  playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=50&key={YOUTUBE_API_KEY}"
  res = requests.get(playlist_url).json()

  videos = []
  for item in res.get("items", []):
    vid = item["contentDetails"]["videoId"]
    title = item["snippet"]["title"]
    published_at = item["contentDetails"]["videoPublishedAt"]
    videos.append(
        {"id": vid, "title": title, "published_at": published_at, "views": 0}
    )

  if not videos:
    return []

  vids_ids = ",".join([v["id"] for v in videos])
  stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet,contentDetails&id={vids_ids}&key={YOUTUBE_API_KEY}"
  stats_res = requests.get(stats_url).json()

  processed_videos = []
  for item in stats_res.get("items", []):
    vid = item["id"]
    views = int(item["statistics"].get("viewCount", 0))
    duration_str = item["contentDetails"].get("duration", "PT0S")
    duration_sec = parse_iso8601_duration(duration_str)

    for v in videos:
      if v["id"] == vid:
        v["views"] = views
        v["channel"] = item["snippet"]["channelTitle"]
        v["duration"] = duration_sec
        if duration_sec > 60:
          processed_videos.append(v)

  return processed_videos


def main():
  if not YOUTUBE_API_KEY:
    print("Не вказано YOUTUBE_API_KEY")
    return

  detected = []
  if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
      try:
        detected = json.load(f)
      except:
        detected = []

  now = datetime.now(timezone.utc)
  seven_days_ago = now - timedelta(days=7)

  updated_detected = []
  for item in detected:
    pub_str = item.get("published_at")
    if pub_str:
      try:
        pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        # Якщо відео новіше або рівно 7 днів — оновлюємо і залишаємо
        if pub_time >= seven_days_ago:
          vid_id = item["id"]
          stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid_id}&key={YOUTUBE_API_KEY}"
          stats_res = requests.get(stats_url).json()
          items = stats_res.get("items", [])
          if items:
            current_views = int(
                items[0]["statistics"].get("viewCount", item["views"])
            )
            item["views"] = current_views

            diff_hours = max((now - pub_time).total_seconds() / 3600, 0.5)
            views_per_hour = int(current_views / diff_hours)
            item["views_per_hour"] = views_per_hour

            median_views = item["norm"]
            multiplier = current_views / median_views if median_views > 0 else 1
            percent_diff = int((multiplier - 1) * 100)
            item["percent"] = percent_diff
            item["score"] = percent_diff + int(views_per_hour * 0.2)

            formatted_date, relative_time = format_time_info(pub_str)
            item["time"] = formatted_date
            item["relative_time"] = relative_time

            msg_id = item.get("telegram_message_id")
            if msg_id:
              msg_text = (
                  f"🔥 *АКТУАЛЬНИЙ ЗАЛЬОТ!*\n\n"
                  f"👤 *Автор:* {item['channel']}\n"
                  f"🎬 *Ролик:* [{item['title']}]({item['url']})\n"
                  f"👁 *Перегляди:* {current_views:,}\n"
                  f"📈 *Норма (медіана):* {median_views:,}\n"
                  f"📊 *Відхилення:* `+{percent_diff}%`\n"
                  f"⚡️ *Швидкість:* `{views_per_hour:,} п/год`\n"
                  f"⏱ *Викладено:* {formatted_date} ({relative_time})"
              )
              edit_telegram_message(msg_id, msg_text)

          updated_detected.append(item)
        else:
          # Якщо минуло більше 7 днів — видаляємо повідомлення з телеграму (з сайту воно пропаде само)
          msg_id = item.get("telegram_message_id")
          if msg_id:
            delete_telegram_message(msg_id)
      except Exception as e:
        print(f"Помилка обробки ролика: {e}")

  seen_ids = {d["id"] for d in updated_detected}

  if not os.path.exists("channels.txt"):
    print("Файл channels.txt не знайдено")
    return

  with open("channels.txt", "r", encoding="utf-8") as f:
    channels = [line.strip() for line in f if line.strip()]

  new_zalyoty = []

  for ch_url in channels:
    print(f"\nПеревірка каналу: {ch_url}")
    ch_id, uploads_id = get_channel_id_by_url(ch_url)
    if not uploads_id:
      print(f"  ❌ Не вдалося знайти канал за посиланням")
      continue

    videos = get_video_stats(uploads_id)
    if len(videos) < 5:
      print(f"  ❌ Занадто мало довгих відео ({len(videos)})")
      continue

    channel_name = videos[0].get("channel", "Unknown")
    print(f"  ✅ Канал: {channel_name} (довгих відео знайдено: {len(videos)})")

    for i, candidate_video in enumerate(videos):
      pub_str = candidate_video["published_at"]
      try:
        pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
      except:
        continue

      if pub_time < seven_days_ago:
        break

      vid_id = candidate_video["id"]
      lat_views = candidate_video["views"]
      title = candidate_video["title"]

      if vid_id in seen_ids:
        continue

      other_videos = [v for j, v in enumerate(videos) if j != i][:15]
      past_views = sorted([v["views"] for v in other_videos])

      if len(past_views) >= 9:
        clean_past = past_views[2:-2]
      elif len(past_views) >= 5:
        clean_past = past_views[1:-1]
      else:
        clean_past = past_views

      if clean_past:
        n = len(clean_past)
        if n % 2 == 1:
          median_views = clean_past[n // 2]
        else:
          median_views = (clean_past[n // 2 - 1] + clean_past[n // 2]) // 2
      else:
        median_views = 1000

      if median_views == 0:
        median_views = 100

      multiplier = lat_views / median_views if median_views > 0 else 1

      diff_hours = max((now - pub_time).total_seconds() / 3600, 0.5)
      views_per_hour = int(lat_views / diff_hours)

      is_zalyot = False
      if lat_views >= 15000 and multiplier >= 2.5:
        print(f"    🔥 ЦЕ ЗАЛЬОТ! Додаємо.")
        is_zalyot = True

      if is_zalyot:
        percent_diff = int((multiplier - 1) * 100)
        formatted_date, relative_time = format_time_info(pub_str)
        priority_score = percent_diff + int(views_per_hour * 0.2)

        msg = (
            f"🔥 *ЗНАЙДЕНО ЗАЛЬОТ!*\n\n"
            f"👤 *Автор:* {channel_name}\n"
            f"🎬 *Ролик:* [{title}](https://www.youtube.com/watch?v={vid_id})\n"
            f"👁 *Перегляди:* {lat_views:,}\n"
            f"📈 *Норма (медіана):* {median_views:,}\n"
            f"📊 *Відхилення:* `+{percent_diff}%`\n"
            f"⚡️ *Швидкість:* `{views_per_hour:,} п/год`\n"
            f"⏱ *Викладено:* {formatted_date} ({relative_time})"
        )
        msg_id = send_telegram(msg)

        item = {
            "id": vid_id,
            "title": title,
            "channel": channel_name,
            "views": lat_views,
            "norm": median_views,
            "percent": percent_diff,
            "views_per_hour": views_per_hour,
            "score": priority_score,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail": f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
            "time": formatted_date,
            "relative_time": relative_time,
            "published_at": pub_str,
            "telegram_message_id": msg_id,
        }
        new_zalyoty.append(item)
        seen_ids.add(vid_id)

  all_data = new_zalyoty + updated_detected
  all_data.sort(key=lambda x: x.get("score", x.get("percent", 0)), reverse=True)

  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)

  print(f"\n✨ Успішно оновлено. Всього зальотів у базі: {len(all_data)}")


if __name__ == "__main__":
  main()
