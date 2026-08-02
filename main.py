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
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
  try:
    requests.post(url, json=payload)
  except Exception as e:
    print(f"Помилка відправки в Telegram: {e}")


def get_channel_id_by_url(url):
  clean_url = url.split("?")[0]
  handle = clean_url.strip("/").split("@")[-1]
  api_url = f"https://www.googleapis.com/youtube/v3/channels?part=id,contentDetails&forHandle={handle}&key={YOUTUBE_API_KEY}"
  res = requests.get(api_url).json()
  items = res.get("items", [])
  if items:
    return (
        items[0]["id"],
        items[0]["contentDetails"]["relatedPlaylists"]["uploads"],
    )
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
  playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=25&key={YOUTUBE_API_KEY}"
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

  seen_ids = {d["id"] for d in detected}

  if not os.path.exists("channels.txt"):
    print("Файл channels.txt не знайдено")
    return

  with open("channels.txt", "r", encoding="utf-8") as f:
    channels = [line.strip() for line in f if line.strip()]

  new_zalyoty = []
  now = datetime.now(timezone.utc)
  seven_days_ago = now - timedelta(days=7)

  for ch_url in channels:
    print(f"\nПеревірка каналу: {ch_url}")
    ch_id, uploads_id = get_channel_id_by_url(ch_url)
    if not uploads_id:
      print(f"  ❌ Не вдалося знайти канал")
      continue

    videos = get_video_stats(uploads_id)
    if len(videos) < 5:
      print(f"  ❌ Занадто мало відео ({len(videos)})")
      continue

    channel_name = videos[0].get("channel", "Unknown")
    print(f"  ✅ Канал: {channel_name} (знайдено відео: {len(videos)})")

    for i, candidate_video in enumerate(videos):
      pub_str = candidate_video["published_at"]
      try:
        pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
      except:
        continue

      if pub_time < seven_days_ago:
        break  # Старіші за 7 днів пропускаємо

      vid_id = candidate_video["id"]
      lat_views = candidate_video["views"]
      title = candidate_video["title"]

      if vid_id in seen_ids:
        print(
            f"    ⏭ Пропущено (вже є в базі): {title} ({lat_views:,} переглядів)"
        )
        continue

      other_videos = [v for j, v in enumerate(videos) if j != i]
      past_views = sorted([v["views"] for v in other_videos])

      if len(past_views) >= 6:
        clean_past = past_views[2:-2]
      else:
        clean_past = past_views

      median_views = (
          clean_past[len(clean_past) // 2] if clean_past else 1000
      )
      if median_views == 0:
        median_views = 100

      multiplier = lat_views / median_views if median_views > 0 else 1
      print(
          f"    🔍 {title[:40]}... | Перегляди: {lat_views:,} | Норма:"
          f" {median_views:,} | Множник: {multiplier:.2f}x"
      )

      # Множник знижено до 2.0, щоб точно піймати великі зальоти
      if lat_views >= (median_views * 2.0) or lat_views >= 30000:
        if multiplier >= 2.0:
          print(f"    🔥 ЦЕ ЗАЛЬОТ! Додаємо.")
          is_zalyot = True
        else:
          is_zalyot = False
      else:
        is_zalyot = False

      if is_zalyot:
        percent_diff = int((multiplier - 1) * 100)
        formatted_date, relative_time = format_time_info(pub_str)

        item = {
            "id": vid_id,
            "title": title,
            "channel": channel_name,
            "views": lat_views,
            "norm": median_views,
            "percent": percent_diff,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "thumbnail": f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
            "time": formatted_date,
            "relative_time": relative_time,
            "published_at": pub_str,
        }
        new_zalyoty.append(item)
        seen_ids.add(vid_id)

        msg = (
            f"🔥 *ЗНАЙДЕНО ЗАЛЬОТ!*\n\n"
            f"👤 *Автор:* {channel_name}\n"
            f"🎬 *Ролик:* [{title}]({item['url']})\n"
            f"👁 *Перегляди:* {lat_views:,}\n"
            f"📈 *Норма (медіана):* {median_views:,}\n"
            f"📊 *Відхилення:* `+{percent_diff}%`\n"
            f"⏱ *Викладено:* {formatted_date} ({relative_time})"
        )
        send_telegram(msg)

  all_data = new_zalyoty + detected

  valid_data = []
  for item in all_data:
    pub_str = item.get("published_at")
    if pub_str:
      try:
        pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        if pub_time >= seven_days_ago:
          valid_data.append(item)
      except:
        pass

  valid_data.sort(key=lambda x: x.get("percent", 0), reverse=True)

  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(valid_data, f, ensure_ascii=False, indent=2)

  print(f"\n✨ Успішно оновлено. Всього зальотів у базі: {len(valid_data)}")


if __name__ == "__main__":
  main()
