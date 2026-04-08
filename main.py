import os
import asyncio
import logging
import requests
import re
import json
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Set
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TikTokDownloaderBot:
    def __init__(self, token: str, admin_id: int = None):
        self.token = token
        self.admin_id = admin_id  # ID của admin (người có quyền broadcast)
        self.download_dir = Path("downloads")
        self.download_dir.mkdir(exist_ok=True)
        
        # File lưu danh sách users
        self.users_file = Path("users.json")
        self.users: Set[int] = self.load_users()
        
        # Lưu trữ tạm thông tin người dùng
        self.user_sessions = {}
        
        # Reply Keyboard
        self.main_keyboard = ReplyKeyboardMarkup(
            [
                ["📥 Tải Video", "🖼️ Tải Ảnh"],
                ["📦 Tải 100 Video từ Kênh", "❓ Hướng dẫn"],
                ["ℹ️ Thông tin Bot", "🗑️ Xóa Keyboard"]
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        # Admin keyboard (thêm nút broadcast)
        if self.admin_id:
            self.admin_keyboard = ReplyKeyboardMarkup(
                [
                    ["📥 Tải Video", "🖼️ Tải Ảnh"],
                    ["📦 Tải 100 Video từ Kênh", "❓ Hướng dẫn"],
                    ["ℹ️ Thông tin Bot", "📢 Broadcast"],
                    ["🗑️ Xóa Keyboard", "📊 Thống kê"]
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
        else:
            self.admin_keyboard = self.main_keyboard
        
        # Cấu hình yt-dlp cho video
        self.ydl_opts_video = {
            'format': 'best',
            'outtmpl': str(self.download_dir / '%(title)s_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'postprocessors': [],
            'extractor_args': {'tiktok': {'no_watermark': ['1']}},
        }
        
        # Cấu hình cho tải hàng loạt
        self.ydl_opts_batch = {
            'format': 'best',
            'outtmpl': str(self.download_dir / '%(channel)s_%(title)s_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'postprocessors': [],
            'extractor_args': {'tiktok': {'no_watermark': ['1']}},
            'ignoreerrors': True,
            'nooverwrites': True,
        }
    
    def load_users(self) -> Set[int]:
        """Tải danh sách users từ file JSON"""
        try:
            if self.users_file.exists():
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('users', []))
        except Exception as e:
            logger.error(f"Lỗi tải users: {e}")
        return set()
    
    def save_users(self):
        """Lưu danh sách users vào file JSON"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump({'users': list(self.users), 'last_updated': time.time()}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Lỗi lưu users: {e}")
    
    def add_user(self, user_id: int):
        """Thêm user mới"""
        if user_id not in self.users:
            self.users.add(user_id)
            self.save_users()
            logger.info(f"✅ Đã thêm user mới: {user_id} (Tổng: {len(self.users)})")
    
    def is_admin(self, user_id: int) -> bool:
        """Kiểm tra có phải admin không"""
        return self.admin_id is not None and user_id == self.admin_id
    
    async def broadcast_message(self, message_text: str, update: Update = None, 
                                photo_url: str = None, document_path: str = None) -> Dict:
        """
        Gửi tin nhắn broadcast tới tất cả users
        
        Returns:
            Dict với thông tin gửi thành công/thất bại
        """
        if not self.users:
            return {'success': 0, 'failed': 0, 'total': 0}
        
        success_count = 0
        failed_count = 0
        
        # Gửi thông báo bắt đầu
        if update:
            await update.message.reply_text(f"📢 Bắt đầu broadcast tới {len(self.users)} users...")
        
        for user_id in self.users:
            try:
                if photo_url:
                    # Gửi ảnh kèm caption
                    await self.application.bot.send_photo(
                        chat_id=user_id,
                        photo=photo_url,
                        caption=message_text,
                        parse_mode='Markdown'
                    )
                elif document_path and os.path.exists(document_path):
                    # Gửi file
                    with open(document_path, 'rb') as f:
                        await self.application.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption=message_text,
                            parse_mode='Markdown'
                        )
                else:
                    # Gửi text thông thường
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode='Markdown'
                    )
                
                success_count += 1
                logger.info(f"✅ Đã gửi broadcast tới {user_id}")
                
                # Delay để tránh spam (0.05 giây)
                await asyncio.sleep(0.05)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Lỗi gửi tới {user_id}: {e}")
                
                # Nếu lỗi liên quan đến bot bị block, có thể xóa user khỏi danh sách
                if "bot was blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                    self.users.discard(user_id)
                    self.save_users()
                    logger.info(f"🗑️ Đã xóa user {user_id} (blocked/deactivated)")
        
        result = {
            'success': success_count,
            'failed': failed_count,
            'total': len(self.users)
        }
        
        # Gửi báo cáo cho admin
        if update:
            report = (
                f"📊 *Báo cáo Broadcast*\n\n"
                f"✅ Thành công: {success_count}\n"
                f"❌ Thất bại: {failed_count}\n"
                f"📊 Tổng số users: {result['total']}\n"
                f"📈 Tỉ lệ thành công: {(success_count/result['total']*100):.1f}%"
            )
            await update.message.reply_text(report, parse_mode='Markdown')
        
        return result
    
    async def broadcast_with_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với xác nhận"""
        user_id = update.effective_user.id
        
        # Kiểm tra quyền admin
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Lấy nội dung broadcast
        text = update.message.text.replace("/broadcast", "").replace("📢 Broadcast", "").strip()
        
        if not text:
            # Hiển thị hướng dẫn
            help_broadcast = (
                "📢 *Hướng dẫn Broadcast*\n\n"
                "Cách sử dụng:\n\n"
                "1️⃣ *Gửi tin nhắn text:*\n"
                "`/broadcast Nội dung tin nhắn`\n\n"
                "2️⃣ *Gửi ảnh kèm caption:*\n"
                "Reply vào ảnh với lệnh:\n"
                "`/broadcast_caption Nội dung caption`\n\n"
                "3️⃣ *Gửi file kèm caption:*\n"
                "Reply vào file với lệnh:\n"
                "`/broadcast_file Nội dung caption`\n\n"
                f"📊 *Tổng số users hiện tại:* {len(self.users)}\n\n"
                "⚠️ *Lưu ý:* Bot sẽ tự động delay 0.05s giữa các tin nhắn để tránh spam!"
            )
            await update.message.reply_text(help_broadcast, parse_mode='Markdown')
            return
        
        # Gửi xác nhận trước khi broadcast
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        context.user_data['broadcast_text'] = text
        context.user_data['broadcast_type'] = 'text'
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast*\n\n"
            f"📝 Nội dung:\n{text[:200]}{'...' if len(text) > 200 else ''}\n\n"
            f"👥 Số lượng người nhận: {len(self.users)}\n\n"
            f"❓ Bạn có chắc chắn muốn gửi?",
            parse_mode='Markdown',
            reply_markup=confirm_keyboard
        )
    
    async def handle_broadcast_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý callback xác nhận broadcast"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await query.edit_message_text("⛔ Bạn không có quyền thực hiện hành động này!")
            return
        
        if query.data.startswith("confirm_broadcast_"):
            admin_id = int(query.data.split("_")[2])
            if admin_id != user_id:
                await query.edit_message_text("❌ Lỗi xác thực!")
                return
            
            # Lấy nội dung broadcast
            broadcast_text = context.user_data.get('broadcast_text', '')
            broadcast_type = context.user_data.get('broadcast_type', 'text')
            broadcast_data = context.user_data.get('broadcast_data', None)
            
            await query.edit_message_text(f"📢 Đang gửi broadcast tới {len(self.users)} users...")
            
            # Thực hiện broadcast
            if broadcast_type == 'text':
                result = await self.broadcast_message(broadcast_text, update)
            elif broadcast_type == 'photo' and broadcast_data:
                result = await self.broadcast_message(broadcast_text, update, photo_url=broadcast_data)
            elif broadcast_type == 'document' and broadcast_data:
                result = await self.broadcast_message(broadcast_text, update, document_path=broadcast_data)
            else:
                await query.edit_message_text("❌ Lỗi: Không xác định được loại broadcast!")
                return
            
            # Xóa dữ liệu tạm
            context.user_data.pop('broadcast_text', None)
            context.user_data.pop('broadcast_type', None)
            context.user_data.pop('broadcast_data', None)
            
        elif query.data == "cancel_broadcast":
            await query.edit_message_text("❌ Đã hủy broadcast!")
            context.user_data.pop('broadcast_text', None)
            context.user_data.pop('broadcast_type', None)
            context.user_data.pop('broadcast_data', None)
    
    async def broadcast_with_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với ảnh"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Kiểm tra reply message có phải ảnh không
        if not update.message.reply_to_message or not update.message.reply_to_message.photo:
            await update.message.reply_text("❌ Vui lòng reply vào ảnh cần broadcast!\n\nVí dụ: Reply vào ảnh và gửi `/broadcast_caption Nội dung`")
            return
        
        # Lấy caption từ lệnh
        caption = update.message.text.replace("/broadcast_caption", "").strip()
        
        if not caption:
            await update.message.reply_text("❌ Vui lòng nhập caption cho ảnh!\n\nVí dụ: `/broadcast_caption Chào các bạn!`")
            return
        
        # Lấy file_id của ảnh
        photo = update.message.reply_to_message.photo[-1]
        file_id = photo.file_id
        
        # Gửi xác nhận
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        context.user_data['broadcast_text'] = caption
        context.user_data['broadcast_type'] = 'photo'
        context.user_data['broadcast_data'] = file_id
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast Ảnh*\n\n"
            f"📝 Caption:\n{caption[:200]}{'...' if len(caption) > 200 else ''}\n\n"
            f"👥 Số lượng người nhận: {len(self.users)}\n\n"
            f"❓ Bạn có chắc chắn muốn gửi?",
            parse_mode='Markdown',
            reply_markup=confirm_keyboard
        )
    
    async def broadcast_with_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với file"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Kiểm tra reply message có phải file không
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Vui lòng reply vào file cần broadcast!\n\nVí dụ: Reply vào file và gửi `/broadcast_file Nội dung`")
            return
        
        # Lấy caption từ lệnh
        caption = update.message.text.replace("/broadcast_file", "").strip()
        
        if not caption:
            await update.message.reply_text("❌ Vui lòng nhập caption cho file!\n\nVí dụ: `/broadcast_file Nội dung`")
            return
        
        # Lấy file_id
        file_obj = None
        if update.message.reply_to_message.document:
            file_obj = update.message.reply_to_message.document
        elif update.message.reply_to_message.video:
            file_obj = update.message.reply_to_message.video
        elif update.message.reply_to_message.audio:
            file_obj = update.message.reply_to_message.audio
        else:
            await update.message.reply_text("❌ Vui lòng reply vào file (document/video/audio)!")
            return
        
        file_id = file_obj.file_id
        
        # Gửi xác nhận
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        context.user_data['broadcast_text'] = caption
        context.user_data['broadcast_type'] = 'document'
        context.user_data['broadcast_data'] = file_id
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast File*\n\n"
            f"📝 Caption:\n{caption[:200]}{'...' if len(caption) > 200 else ''}\n"
            f"📁 Loại file: {file_obj.mime_type}\n\n"
            f"👥 Số lượng người nhận: {len(self.users)}\n\n"
            f"❓ Bạn có chắc chắn muốn gửi?",
            parse_mode='Markdown',
            reply_markup=confirm_keyboard
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xem thống kê bot"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        stats_text = (
            "📊 *Thống kê Bot*\n\n"
            f"👥 *Tổng số users:* {len(self.users)}\n"
            f"📅 *Users đã lưu:* {len(self.users)}\n\n"
            f"💾 *Dung lượng lưu trữ:*\n"
            f"• Users file: {self.users_file.stat().st_size / 1024:.2f} KB\n\n"
            f"📁 *Thư mục downloads:*\n"
            f"• Đường dẫn: {self.download_dir.absolute()}\n"
        )
        
        # Thêm danh sách users gần đây (10 user đầu)
        if self.users:
            recent_users = list(self.users)[-10:]
            stats_text += f"\n🆔 *Users gần đây:*\n"
            for uid in recent_users:
                stats_text += f"• `{uid}`\n"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    def is_photo_link(self, url: str) -> bool:
        """Kiểm tra có phải link ảnh TikTok không"""
        return '/photo/' in url or '/p/' in url
    
    def get_tiktok_image_urls(self, url: str) -> List[str]:
        """Lấy URL ảnh từ TikTok bằng API không chính thức"""
        try:
            api_url = "https://www.tikwm.com/api/"
            
            params = {
                'url': url,
                'count': 12,
                'cursor': 0,
                'web': 1,
                'hd': 1
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(api_url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == 0 and data.get('data'):
                    images = []
                    
                    if data['data'].get('images'):
                        images = data['data']['images']
                    elif data['data'].get('image'):
                        images = [data['data']['image']]
                    
                    if images:
                        hd_images = [img.replace('720x720', '1080x1080') for img in images]
                        return hd_images
                        
            return []
            
        except Exception as e:
            logger.error(f"Lỗi lấy URL ảnh từ API: {e}")
            return []
    
    async def get_channel_videos(self, username: str, limit: int = 100) -> List[Dict]:
        """Lấy danh sách video từ kênh TikTok"""
        try:
            channel_url = f"https://www.tiktok.com/@{username}"
            
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                
                if info and 'entries' in info:
                    videos = []
                    for entry in info['entries'][:limit]:
                        if entry:
                            video_info = {
                                'id': entry.get('id'),
                                'title': entry.get('title', 'No title'),
                                'url': f"https://www.tiktok.com/@{username}/video/{entry.get('id')}",
                                'duration': entry.get('duration', 0)
                            }
                            videos.append(video_info)
                    return videos
            
            return []
            
        except Exception as e:
            logger.error(f"Lỗi lấy danh sách video từ kênh {username}: {e}")
            return []
    
    async def download_batch_videos(self, videos: List[Dict], progress_callback=None) -> List[str]:
        """Tải nhiều video cùng lúc"""
        downloaded_files = []
        total = len(videos)
        
        for idx, video in enumerate(videos):
            try:
                if progress_callback:
                    await progress_callback(idx + 1, total, video['title'])
                
                with yt_dlp.YoutubeDL(self.ydl_opts_batch) as ydl:
                    info = ydl.extract_info(video['url'], download=True)
                    filepath = ydl.prepare_filename(info)
                    
                    if os.path.exists(filepath):
                        downloaded_files.append(filepath)
                    else:
                        base_path = filepath.rsplit('.', 1)[0]
                        for ext in ['.mp4', '.webm', '.mkv']:
                            test_path = base_path + ext
                            if os.path.exists(test_path):
                                downloaded_files.append(test_path)
                                break
                                
            except Exception as e:
                logger.error(f"Lỗi tải video {video['url']}: {e}")
                continue
        
        return downloaded_files
    
    async def download_tiktok_video(self, url: str) -> Optional[Tuple[str, str]]:
        """Tải video TikTok không logo"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts_video) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                
                if not os.path.exists(filepath):
                    base_path = filepath.rsplit('.', 1)[0]
                    for ext in ['.mp4', '.webm', '.mkv']:
                        test_path = base_path + ext
                        if os.path.exists(test_path):
                            filepath = test_path
                            break
                
                if not os.path.exists(filepath):
                    return None, None
                
                return filepath, 'video'
                
        except Exception as e:
            logger.error(f"Lỗi tải video TikTok: {e}")
            return None, None
    
    async def download_tiktok_images(self, url: str) -> Optional[List[Tuple[str, str]]]:
        """Tải ảnh từ TikTok"""
        try:
            image_urls = self.get_tiktok_image_urls(url)
            
            if not image_urls:
                try:
                    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info.get('thumbnails'):
                            thumbnails = info.get('thumbnails', [])
                            if thumbnails:
                                image_urls = [thumbnails[-1].get('url')]
                except:
                    pass
            
            if not image_urls:
                return None
            
            image_files = []
            for idx, img_url in enumerate(image_urls):
                try:
                    img_ext = img_url.split('.')[-1].split('?')[0]
                    if img_ext not in ['jpg', 'jpeg', 'png', 'webp']:
                        img_ext = 'jpg'
                    
                    img_path = self.download_dir / f"tiktok_image_{idx+1}_{int(time.time())}.{img_ext}"
                    
                    response = requests.get(img_url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    if response.status_code == 200:
                        with open(img_path, 'wb') as f:
                            f.write(response.content)
                        image_files.append((str(img_path), 'image'))
                        
                except Exception as e:
                    logger.error(f"Lỗi tải ảnh {idx+1}: {e}")
                    continue
            
            return image_files if image_files else None
                
        except Exception as e:
            logger.error(f"Lỗi tải ảnh TikTok: {e}")
            return None
    
    async def download_tiktok_content(self, url: str) -> Optional[Tuple]:
        """Phân loại và tải nội dung TikTok"""
        if self.is_photo_link(url):
            logger.info("Phát hiện link ảnh TikTok")
            images_result = await self.download_tiktok_images(url)
            if images_result:
                return ('images', images_result)
        
        logger.info("Thử tải video TikTok")
        video_result = await self.download_tiktok_video(url)
        if video_result and video_result[0]:
            return ('video', [video_result])
        
        if not self.is_photo_link(url):
            logger.info("Thử tải ảnh TikTok")
            images_result = await self.download_tiktok_images(url)
            if images_result:
                return ('images', images_result)
        
        return None
    
    async def send_and_delete(self, update: Update, files: List[Tuple[str, str]], content_type: str):
        """Gửi file lên Telegram và xóa ngay"""
        try:
            if content_type == 'video':
                filepath, _ = files[0]
                file_size = os.path.getsize(filepath) / (1024 * 1024)
                
                if file_size > 50:
                    await update.message.reply_text(f"⚠️ Video quá lớn ({file_size:.1f}MB). Telegram giới hạn 50MB!")
                else:
                    with open(filepath, 'rb') as file:
                        await update.message.reply_video(
                            video=file,
                            caption="✅ Đã tải video thành công! (Không logo)",
                            supports_streaming=True,
                            write_timeout=60
                        )
                os.remove(filepath)
                logger.info(f"✅ Đã xóa video: {filepath}")
                
            elif content_type == 'images':
                if not files:
                    await update.message.reply_text("❌ Không có ảnh để gửi!")
                    return
                
                for idx, (filepath, _) in enumerate(files):
                    try:
                        with open(filepath, 'rb') as file:
                            caption = f"✅ Ảnh {idx+1}/{len(files)}" if len(files) > 1 else "✅ Đã tải ảnh thành công!"
                            await update.message.reply_photo(
                                photo=file,
                                caption=caption
                            )
                        os.remove(filepath)
                        logger.info(f"✅ Đã xóa ảnh: {filepath}")
                    except Exception as e:
                        logger.error(f"Lỗi gửi ảnh {idx+1}: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Lỗi gửi lên Telegram: {e}")
            for filepath, _ in files:
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
            await update.message.reply_text(f"❌ Lỗi gửi file: {str(e)[:100]}")
            return False
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý tin nhắn từ người dùng"""
        user_id = update.effective_user.id
        
        # Lưu user vào database
        self.add_user(user_id)
        
        user_input = update.message.text.strip()
        
        # Chọn keyboard phù hợp
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        
        # Xử lý các lệnh từ keyboard
        if user_input == "📥 Tải Video":
            await update.message.reply_text(
                "📥 *Chế độ tải video*\n\nVui lòng gửi link video TikTok vào đây:\n\nVí dụ: `https://www.tiktok.com/@username/video/123456789`",
                parse_mode='Markdown',
                reply_markup=current_keyboard
            )
            return
            
        elif user_input == "🖼️ Tải Ảnh":
            await update.message.reply_text(
                "🖼️ *Chế độ tải ảnh*\n\nVui lòng gửi link bài đăng ảnh TikTok vào đây:\n\nVí dụ: `https://www.tiktok.com/@username/photo/123456789`",
                parse_mode='Markdown',
                reply_markup=current_keyboard
            )
            return
            
        elif user_input == "📦 Tải 100 Video từ Kênh":
            await update.message.reply_text(
                "📦 *Tải 100 Video mới nhất từ kênh*\n\nVui lòng nhập username TikTok (không bao gồm @):\n\nVí dụ: `tiktok` hoặc `username`\n\n⚠️ Quá trình tải có thể mất vài phút.",
                parse_mode='Markdown',
                reply_markup=current_keyboard
            )
            context.user_data['waiting_for_username'] = True
            return
            
        elif user_input == "📢 Broadcast" and self.is_admin(user_id):
            await self.broadcast_with_confirmation(update, context)
            return
            
        elif user_input == "📊 Thống kê" and self.is_admin(user_id):
            await self.stats_command(update, context)
            return
            
        elif user_input == "❓ Hướng dẫn":
            help_text = (
                "📖 *Hướng dẫn sử dụng:*\n\n"
                "1️⃣ *Tải video:*\n"
                "   • Chọn '📥 Tải Video'\n"
                "   • Gửi link video TikTok\n\n"
                "2️⃣ *Tải ảnh:*\n"
                "   • Chọn '🖼️ Tải Ảnh'\n"
                "   • Gửi link bài đăng ảnh\n\n"
                "3️⃣ *Tải 100 video:*\n"
                "   • Chọn '📦 Tải 100 Video từ Kênh'\n"
                "   • Nhập username TikTok\n\n"
                "4️⃣ *Xóa keyboard:*\n"
                "   • Chọn '🗑️ Xóa Keyboard'\n\n"
                "⚡ *Tính năng:*\n"
                "• Không logo, không watermark\n"
                "• Xóa file ngay sau khi gửi\n"
                "• Tốc độ tải nhanh"
            )
            if self.is_admin(user_id):
                help_text += "\n\n👑 *Tính năng Admin:*\n• 📢 Broadcast tin nhắn tới all users\n• 📊 Xem thống kê bot"
            
            await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=current_keyboard)
            return
            
        elif user_input == "ℹ️ Thông tin Bot":
            info_text = (
                "ℹ️ *Thông tin Bot:*\n\n"
                "🤖 *Tên:* TikTok Downloader Bot\n"
                "📅 *Phiên bản:* 2.1 (Có Broadcast)\n"
                "✨ *Tính năng:*\n"
                "• Tải video không logo\n"
                "• Tải ảnh chất lượng cao\n"
                "• Tải 100 video mới nhất\n"
                "• Xóa file tự động\n"
                "• 📢 Broadcast thông báo\n\n"
                "⚙️ *Giới hạn:*\n"
                "• Video tối đa 50MB\n"
                "• Tải hàng loạt tối đa 100 video\n\n"
                f"👥 *Tổng số người dùng:* {len(self.users)}\n\n"
                "💡 *Mọi thắc mắc:* Liên hệ @admin"
            )
            await update.message.reply_text(info_text, parse_mode='Markdown', reply_markup=current_keyboard)
            return
            
        elif user_input == "🗑️ Xóa Keyboard":
            # Xóa keyboard
            remove_keyboard = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text(
                "✅ Đã xóa keyboard. Gửi /start để hiện lại!",
                reply_markup=remove_keyboard
            )
            return
        
        # Xử lý nhập username cho tải hàng loạt
        if context.user_data.get('waiting_for_username'):
            username = user_input.replace('@', '')
            context.user_data['waiting_for_username'] = False
            await self.process_batch_download(update, username)
            return
        
        # Xử lý link TikTok
        tiktok_domains = ['tiktok.com', 'vm.tiktok.com', 'www.tiktok.com', 'vt.tiktok.com']
        if any(domain in user_input for domain in tiktok_domains):
            status_msg = await update.message.reply_text("🔄 Đang tải nội dung không logo...")
            
            try:
                result = await self.download_tiktok_content(user_input)
                
                if not result:
                    await status_msg.edit_text("❌ Không thể tải nội dung. Vui lòng kiểm tra link!")
                    return
                
                content_type, files = result
                
                if not files:
                    await status_msg.edit_text("❌ Không tìm thấy nội dung để tải!")
                    return
                
                await status_msg.edit_text("📤 Đang gửi lên Telegram...")
                success = await self.send_and_delete(update, files, content_type)
                
                if success:
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ Gửi thất bại!")
                    
            except Exception as e:
                logger.error(f"Lỗi xử lý: {e}")
                await status_msg.edit_text(f"❌ Có lỗi xảy ra: {str(e)[:100]}")
        else:
            await update.message.reply_text(
                "⚠️ Vui lòng sử dụng các nút bên dưới hoặc gửi link TikTok hợp lệ!",
                reply_markup=current_keyboard
            )
    
    async def process_batch_download(self, update: Update, username: str):
        """Xử lý tải hàng loạt"""
        status_msg = await update.message.reply_text(f"🔄 Đang lấy danh sách video từ @{username}...")
        
        try:
            videos = await self.get_channel_videos(username, limit=100)
            
            if not videos:
                await status_msg.edit_text(f"❌ Không tìm thấy kênh @{username} hoặc kênh không có video!")
                return
            
            await status_msg.edit_text(f"✅ Tìm thấy {len(videos)} video. Bắt đầu tải...")
            
            progress_msg = await update.message.reply_text("📥 Đang tải video...\n0%")
            
            async def update_progress(current, total, title):
                percent = (current / total) * 100
                await progress_msg.edit_text(
                    f"📥 Đang tải video...\n"
                    f"📊 Tiến độ: {percent:.1f}% ({current}/{total})\n"
                    f"🎬 Đang tải: {title[:30]}..."
                )
            
            downloaded_files = await self.download_batch_videos(videos, update_progress)
            
            if not downloaded_files:
                await progress_msg.edit_text("❌ Không thể tải video nào!")
                return
            
            await progress_msg.edit_text(f"📤 Đã tải xong {len(downloaded_files)}/{len(videos)} video. Đang gửi lên Telegram...")
            
            success_count = 0
            for filepath in downloaded_files:
                try:
                    with open(filepath, 'rb') as file:
                        await update.message.reply_video(
                            video=file,
                            caption=f"✅ Video {success_count + 1}/{len(downloaded_files)} từ @{username}",
                            supports_streaming=True
                        )
                    os.remove(filepath)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Lỗi gửi video: {e}")
                    continue
            
            await progress_msg.delete()
            
            current_keyboard = self.admin_keyboard if self.is_admin(update.effective_user.id) else self.main_keyboard
            await update.message.reply_text(
                f"✅ Hoàn thành!\n"
                f"📊 Đã tải thành công: {success_count}/{len(downloaded_files)} video\n"
                f"🎬 Từ kênh: @{username}",
                reply_markup=current_keyboard
            )
            
        except Exception as e:
            logger.error(f"Lỗi tải hàng loạt: {e}")
            await status_msg.edit_text(f"❌ Lỗi: {str(e)[:100]}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý lệnh /start với keyboard"""
        user_id = update.effective_user.id
        self.add_user(user_id)
        
        welcome_msg = (
            "🤖 *TikTok Downloader Bot*\n\n"
            "✨ *Chào mừng bạn đến với bot!*\n\n"
            "📌 *Tính năng:*\n"
            "• ✅ Tải video TikTok *không logo*\n"
            "• ✅ Tải ảnh TikTok chất lượng cao\n"
            "• ✅ Tải 100 video mới nhất từ kênh\n"
            "• ✅ Xóa file ngay sau khi gửi\n\n"
            "💡 *Sử dụng các nút bên dưới để bắt đầu:*"
        )
        
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=current_keyboard)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý lệnh /help"""
        user_id = update.effective_user.id
        help_text = (
            "📖 *Hướng dẫn sử dụng:*\n\n"
            "1️⃣ *Tải video:*\n"
            "   • Chọn '📥 Tải Video'\n"
            "   • Gửi link video TikTok\n\n"
            "2️⃣ *Tải ảnh:*\n"
            "   • Chọn '🖼️ Tải Ảnh'\n"
            "   • Gửi link bài đăng ảnh\n\n"
            "3️⃣ *Tải 100 video:*\n"
            "   • Chọn '📦 Tải 100 Video từ Kênh'\n"
            "   • Nhập username TikTok\n\n"
            "4️⃣ *Xóa keyboard:*\n"
            "   • Chọn '🗑️ Xóa Keyboard'\n\n"
            "⚙️ *Các lệnh:*\n"
            "/start - Hiện keyboard\n"
            "/help - Hướng dẫn"
        )
        
        if self.is_admin(user_id):
            help_text += "\n\n👑 *Lệnh Admin:*\n/broadcast - Gửi tin nhắn tới tất cả users\n/stats - Xem thống kê bot"
        
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=current_keyboard)
    
    def run(self):
        """Chạy bot"""
        application = Application.builder().token(self.token).build()
        self.application = application  # Lưu để dùng trong broadcast
        
        # Thêm handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("broadcast", self.broadcast_with_confirmation))
        application.add_handler(CommandHandler("broadcast_caption", self.broadcast_with_photo))
        application.add_handler(CommandHandler("broadcast_file", self.broadcast_with_file))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CallbackQueryHandler(self.handle_broadcast_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        print("🚀 Bot đang chạy...")
        print("📌 Tính năng: Tải video & ảnh TikTok không logo + Tải 100 video từ kênh")
        print("✅ Hỗ trợ Reply Keyboard trên thanh nhắn tin")
        print(f"👥 Đã lưu {len(self.users)} users")
        if self.admin_id:
            print(f"👑 Admin ID: {self.admin_id}")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import time
    BOT_TOKEN = "8785070280:AAFVOnED_YtifSAoOWPS6Naesk44sKEOX2E"
    ADMIN_ID = 123456789  # ⚠️ THAY THẾ BẰNG ID TELEGRAM CỦA BẠN
    
    if not BOT_TOKEN:
        print("❌ Vui lòng cấu hình BOT_TOKEN!")
    else:
        print("🤖 Khởi động TikTok Downloader Bot...")
        print(f"✅ Token: {BOT_TOKEN[:15]}...")
        if ADMIN_ID == 5464983623:
            print("⚠️ CẢNH BÁO: Bạn chưa cấu hình ADMIN_ID!")
            print("📌 Để có quyền broadcast, hãy thay ADMIN_ID bằng ID Telegram của bạn")
            print("🔍 Tìm ID của bạn: Gửi tin nhắn @userinfobot trên Telegram\n")
        
        bot = TikTokDownloaderBot(BOT_TOKEN, admin_id=ADMIN_ID)
        bot.run()
