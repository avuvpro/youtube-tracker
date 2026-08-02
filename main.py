from datetime import datetime, timezone
import json
import os
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DATA_FILE = "data.json"


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


def get_video_stats(playlist_id):
  playlist_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=20&key={YOUTUBE_API_KEY}"
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
  stats_url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={vids_ids}&key={YOUTUBE_API_KEY}"
  stats_res = requests.get(stats_url).json()

  for item in stats_res.get("items", []):
    vid = item["id"]
    views = int(item["statistics"].get("viewCount", 0))
    for v in videos:
      if v["id"] == vid:
        v["views"] = views
        v["channel"] = item["snippet"]["channelTitle"]

  return videos


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

  for ch_url in channels:
    ch_id, uploads_id = get_channel_id_by_url(ch_url)
    if not uploads_id:
      continue

    videos = get_video_stats(uploads_id)
    if not videos:
      continue

    channel_name = videos[0].get("channel", "Unknown")

    past_videos = videos[1:]
    past_views = sorted([v["views"] for v in past_videos]) if past_videos else [100]

    if len(past_views) >= 6:
      clean_past = past_views[2:-2]
    else:
      clean_past = past_views

    median_views = (
        clean_past[len(clean_past) // 2] if clean_past else 100
    )
    if median_views == 0:
      median_views = 100

    latest_video = videos[0]
    lat_views = latest_video["views"]
    vid_id = latest_video["id"]

    if vid_id in seen_ids:
      continue

    # РОБИМО КОЖНЕ ОСТАННЄ ВІДЕО ЗАЛЬОТОМ
    is_zalyot = True
    multiplier = lat_views / median_views if median_views > 0 else 2.0

    if is_zalyot:
      percent_diff = int((multiplier - 1) * 100) if median_views > 0 else 100
      item = {
          "id": vid_id,
          "title": latest_video["title"],
          "channel": channel_name,
          "views": lat_views,
          "norm": median_views,
          "percent": percent_diff,
          "url": f"https://www.youtube.com/watch?v={vid_id}",
          "thumbnail": f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
          "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
      }
      new_zalyoty.append(item)

      msg = (
          f"🔥 *ОСТАННЄ ВІДЕО ЗАЛЬОТ!*\n\n"
          f"👤 *Автор:* {channel_name}\n"
          f"🎬 *Ролик:* [{latest_video['title']}]({item['url']})\n"
          f"👁 *Перегляди:* {lat_views:,}\n"
          f"📈 *Норма:* {median_views:,}"
      )
      send_telegram(msg)

  if new_zalyoty:
    all_data = new_zalyoty + detected
    with open(DATA_FILE, "w", encoding="utf-8") as f:
      json.dump(all_data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
  main()
