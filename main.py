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
        self.admin_id = admin_id
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
        
        # Admin keyboard
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
        
        # Cấu hình yt-dlp
        self.ydl_opts_video = {
            'format': 'best',
            'outtmpl': str(self.download_dir / '%(title)s_%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'postprocessors': [],
            'extractor_args': {'tiktok': {'no_watermark': ['1']}},
        }
        
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
    
    async def broadcast_message(self, message_text: str, context: ContextTypes.DEFAULT_TYPE, 
                                reply_to_admin=None, photo_id: str = None, 
                                document_id: str = None, video_id: str = None) -> Dict:
        """
        Gửi tin nhắn broadcast tới tất cả users
        """
        if not self.users:
            if reply_to_admin:
                await reply_to_admin.reply_text("❌ Không có users nào để broadcast!")
            return {'success': 0, 'failed': 0, 'total': 0}
        
        success_count = 0
        failed_count = 0
        
        # Gửi thông báo bắt đầu nếu có admin message
        if reply_to_admin:
            await reply_to_admin.reply_text(f"📢 Bắt đầu broadcast tới {len(self.users)} users...\n⏱️ Quá trình này có thể mất vài phút.")
        
        for idx, user_id in enumerate(self.users):
            try:
                # Gửi tin nhắn theo loại
                if photo_id:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=photo_id,
                        caption=message_text,
                        parse_mode='Markdown'
                    )
                elif document_id:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=document_id,
                        caption=message_text,
                        parse_mode='Markdown'
                    )
                elif video_id:
                    await context.bot.send_video(
                        chat_id=user_id,
                        video=video_id,
                        caption=message_text,
                        parse_mode='Markdown'
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode='Markdown'
                    )
                
                success_count += 1
                
                # Cập nhật tiến độ mỗi 10 users
                if reply_to_admin and (idx + 1) % 10 == 0:
                    try:
                        await reply_to_admin.reply_text(
                            f"📊 Tiến độ: {idx + 1}/{len(self.users)} users\n"
                            f"✅ Thành công: {success_count}\n"
                            f"❌ Thất bại: {failed_count}"
                        )
                    except:
                        pass
                
                # Delay để tránh spam
                await asyncio.sleep(0.05)
                
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Lỗi gửi tới {user_id}: {e}")
                
                # Xóa user nếu bot bị block
                if "bot was blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                    self.users.discard(user_id)
                    self.save_users()
                    logger.info(f"🗑️ Đã xóa user {user_id}")
        
        # Lưu lại users sau khi xóa
        self.save_users()
        
        # Gửi báo cáo cuối cùng
        if reply_to_admin:
            report = (
                f"✅ *Broadcast hoàn tất!*\n\n"
                f"👥 Tổng số users: {len(self.users)}\n"
                f"✅ Thành công: {success_count}\n"
                f"❌ Thất bại: {failed_count}\n"
                f"📈 Tỉ lệ thành công: {(success_count/len(self.users)*100):.1f}%"
            )
            await reply_to_admin.reply_text(report, parse_mode='Markdown')
        
        return {'success': success_count, 'failed': failed_count, 'total': len(self.users)}
    
    async def broadcast_with_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với xác nhận"""
        user_id = update.effective_user.id
        
        # Kiểm tra quyền admin
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Lấy nội dung broadcast (bỏ qua lệnh /broadcast hoặc nút bấm)
        text = update.message.text
        if text.startswith("/broadcast"):
            text = text.replace("/broadcast", "").strip()
        elif text == "📢 Broadcast":
            text = ""
        
        if not text:
            help_broadcast = (
                "📢 *Hướng dẫn Broadcast*\n\n"
                "*Cách gửi tin nhắn text:*\n"
                "`/broadcast Nội dung tin nhắn`\n\n"
                "*Cách gửi ảnh kèm caption:*\n"
                "1. Reply vào ảnh cần gửi\n"
                "2. Gửi lệnh: `/broadcast_caption Nội dung caption`\n\n"
                "*Cách gửi video kèm caption:*\n"
                "1. Reply vào video cần gửi\n"
                "2. Gửi lệnh: `/broadcast_video Nội dung caption`\n\n"
                f"📊 *Tổng số users:* {len(self.users)}\n\n"
                "⚠️ *Lưu ý:* Bot sẽ tự động delay 0.05s giữa các tin nhắn"
            )
            await update.message.reply_text(help_broadcast, parse_mode='Markdown')
            return
        
        # Lưu nội dung broadcast
        context.user_data['broadcast_text'] = text
        context.user_data['broadcast_type'] = 'text'
        
        # Gửi xác nhận
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast*\n\n"
            f"📝 Nội dung:\n{text[:300]}{'...' if len(text) > 300 else ''}\n\n"
            f"👥 Số lượng người nhận: {len(self.users)}\n\n"
            f"❓ Bạn có chắc chắn muốn gửi?",
            parse_mode='Markdown',
            reply_markup=confirm_keyboard
        )
    
    async def broadcast_with_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với ảnh"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Kiểm tra reply message
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Vui lòng reply vào ảnh cần broadcast!\n\nVí dụ: Reply vào ảnh và gửi `/broadcast_caption Nội dung`")
            return
        
        # Kiểm tra có phải ảnh không
        if not update.message.reply_to_message.photo:
            await update.message.reply_text("❌ Vui lòng reply vào ẢNH (photo)!\n\nVí dụ: Reply vào ảnh và gửi lệnh")
            return
        
        # Lấy caption
        caption = update.message.text.replace("/broadcast_caption", "").strip()
        if not caption:
            await update.message.reply_text("❌ Vui lòng nhập caption cho ảnh!\n\nVí dụ: `/broadcast_caption Chào các bạn!`")
            return
        
        # Lấy file_id của ảnh chất lượng cao nhất
        photo = update.message.reply_to_message.photo[-1]
        photo_id = photo.file_id
        
        # Lưu thông tin
        context.user_data['broadcast_text'] = caption
        context.user_data['broadcast_type'] = 'photo'
        context.user_data['broadcast_file_id'] = photo_id
        
        # Gửi xác nhận
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast Ảnh*\n\n"
            f"📝 Caption:\n{caption[:300]}{'...' if len(caption) > 300 else ''}\n\n"
            f"👥 Số lượng người nhận: {len(self.users)}\n\n"
            f"❓ Bạn có chắc chắn muốn gửi?",
            parse_mode='Markdown',
            reply_markup=confirm_keyboard
        )
    
    async def broadcast_with_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xử lý broadcast với video"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        # Kiểm tra reply message
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Vui lòng reply vào video cần broadcast!\n\nVí dụ: Reply vào video và gửi `/broadcast_video Nội dung`")
            return
        
        # Kiểm tra có phải video không
        if not update.message.reply_to_message.video:
            await update.message.reply_text("❌ Vui lòng reply vào VIDEO!\n\nVí dụ: Reply vào video và gửi lệnh")
            return
        
        # Lấy caption
        caption = update.message.text.replace("/broadcast_video", "").strip()
        if not caption:
            await update.message.reply_text("❌ Vui lòng nhập caption cho video!\n\nVí dụ: `/broadcast_video Chào các bạn!`")
            return
        
        # Lấy file_id của video
        video = update.message.reply_to_message.video
        video_id = video.file_id
        
        # Lưu thông tin
        context.user_data['broadcast_text'] = caption
        context.user_data['broadcast_type'] = 'video'
        context.user_data['broadcast_file_id'] = video_id
        
        # Gửi xác nhận
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_broadcast")
            ]
        ])
        
        await update.message.reply_text(
            f"📢 *Xác nhận Broadcast Video*\n\n"
            f"📝 Caption:\n{caption[:300]}{'...' if len(caption) > 300 else ''}\n\n"
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
            broadcast_file_id = context.user_data.get('broadcast_file_id', None)
            
            await query.edit_message_text(f"📢 Đang gửi broadcast tới {len(self.users)} users...\n⏱️ Vui lòng chờ...")
            
            # Thực hiện broadcast
            if broadcast_type == 'text':
                result = await self.broadcast_message(
                    broadcast_text, 
                    context, 
                    reply_to_admin=await query.message.reply_text("🔄 Đang xử lý...")
                )
            elif broadcast_type == 'photo' and broadcast_file_id:
                # Xóa message tạm thời
                temp_msg = await query.message.reply_text("🔄 Đang gửi ảnh broadcast...")
                result = await self.broadcast_message(
                    broadcast_text, 
                    context, 
                    reply_to_admin=temp_msg,
                    photo_id=broadcast_file_id
                )
            elif broadcast_type == 'video' and broadcast_file_id:
                temp_msg = await query.message.reply_text("🔄 Đang gửi video broadcast...")
                result = await self.broadcast_message(
                    broadcast_text, 
                    context, 
                    reply_to_admin=temp_msg,
                    video_id=broadcast_file_id
                )
            else:
                await query.edit_message_text("❌ Lỗi: Không xác định được loại broadcast!")
                return
            
            # Xóa dữ liệu tạm
            context.user_data.pop('broadcast_text', None)
            context.user_data.pop('broadcast_type', None)
            context.user_data.pop('broadcast_file_id', None)
            
        elif query.data == "cancel_broadcast":
            await query.edit_message_text("❌ Đã hủy broadcast!")
            context.user_data.pop('broadcast_text', None)
            context.user_data.pop('broadcast_type', None)
            context.user_data.pop('broadcast_file_id', None)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Xem thống kê bot"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("⛔ Bạn không có quyền sử dụng tính năng này!")
            return
        
        stats_text = (
            "📊 *Thống kê Bot*\n\n"
            f"👥 *Tổng số users:* {len(self.users)}\n"
            f"📅 *Users đã đăng ký:* {len(self.users)}\n\n"
            f"💾 *Dữ liệu:*\n"
            f"• File users: {self.users_file.stat().st_size / 1024:.2f} KB\n\n"
            f"📁 *Thư mục downloads:*\n"
            f"• {self.download_dir.absolute()}\n"
        )
        
        # Thêm danh sách users gần đây
        if self.users:
            recent_users = list(self.users)[-10:]
            stats_text += f"\n🆔 *10 users gần đây:*\n"
            for uid in recent_users:
                stats_text += f"• `{uid}`\n"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    # Các hàm xử lý TikTok (giữ nguyên từ code gốc)
    def is_photo_link(self, url: str) -> bool:
        return '/photo/' in url or '/p/' in url
    
    def get_tiktok_image_urls(self, url: str) -> List[str]:
        try:
            api_url = "https://www.tikwm.com/api/"
            params = {'url': url, 'count': 12, 'cursor': 0, 'web': 1, 'hd': 1}
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(api_url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 0 and data.get('data'):
                    images = data['data'].get('images', []) or ([data['data'].get('image')] if data['data'].get('image') else [])
                    if images:
                        return [img.replace('720x720', '1080x1080') for img in images]
            return []
        except Exception as e:
            logger.error(f"Lỗi lấy URL ảnh: {e}")
            return []
    
    async def get_channel_videos(self, username: str, limit: int = 100) -> List[Dict]:
        try:
            channel_url = f"https://www.tiktok.com/@{username}"
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if info and 'entries' in info:
                    videos = []
                    for entry in info['entries'][:limit]:
                        if entry:
                            videos.append({
                                'id': entry.get('id'),
                                'title': entry.get('title', 'No title'),
                                'url': f"https://www.tiktok.com/@{username}/video/{entry.get('id')}",
                                'duration': entry.get('duration', 0)
                            })
                    return videos
            return []
        except Exception as e:
            logger.error(f"Lỗi lấy video từ kênh: {e}")
            return []
    
    async def download_batch_videos(self, videos: List[Dict], progress_callback=None) -> List[str]:
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
                logger.error(f"Lỗi tải video: {e}")
                continue
        return downloaded_files
    
    async def download_tiktok_video(self, url: str) -> Optional[Tuple[str, str]]:
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
                return (filepath, 'video') if os.path.exists(filepath) else (None, None)
        except Exception as e:
            logger.error(f"Lỗi tải video: {e}")
            return None, None
    
    async def download_tiktok_images(self, url: str) -> Optional[List[Tuple[str, str]]]:
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
                    response = requests.get(img_url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
                    if response.status_code == 200:
                        with open(img_path, 'wb') as f:
                            f.write(response.content)
                        image_files.append((str(img_path), 'image'))
                except Exception as e:
                    logger.error(f"Lỗi tải ảnh: {e}")
                    continue
            return image_files if image_files else None
        except Exception as e:
            logger.error(f"Lỗi tải ảnh: {e}")
            return None
    
    async def download_tiktok_content(self, url: str) -> Optional[Tuple]:
        if self.is_photo_link(url):
            images_result = await self.download_tiktok_images(url)
            if images_result:
                return ('images', images_result)
        video_result = await self.download_tiktok_video(url)
        if video_result and video_result[0]:
            return ('video', [video_result])
        if not self.is_photo_link(url):
            images_result = await self.download_tiktok_images(url)
            if images_result:
                return ('images', images_result)
        return None
    
    async def send_and_delete(self, update: Update, files: List[Tuple[str, str]], content_type: str):
        try:
            if content_type == 'video':
                filepath, _ = files[0]
                file_size = os.path.getsize(filepath) / (1024 * 1024)
                if file_size > 50:
                    await update.message.reply_text(f"⚠️ Video quá lớn ({file_size:.1f}MB). Telegram giới hạn 50MB!")
                else:
                    with open(filepath, 'rb') as file:
                        await update.message.reply_video(video=file, caption="✅ Đã tải video thành công! (Không logo)", supports_streaming=True, write_timeout=60)
                os.remove(filepath)
            elif content_type == 'images':
                for idx, (filepath, _) in enumerate(files):
                    try:
                        with open(filepath, 'rb') as file:
                            caption = f"✅ Ảnh {idx+1}/{len(files)}" if len(files) > 1 else "✅ Đã tải ảnh thành công!"
                            await update.message.reply_photo(photo=file, caption=caption)
                        os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Lỗi gửi ảnh: {e}")
            return True
        except Exception as e:
            logger.error(f"Lỗi gửi file: {e}")
            for filepath, _ in files:
                try:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
            await update.message.reply_text(f"❌ Lỗi gửi file: {str(e)[:100]}")
            return False
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.add_user(user_id)
        user_input = update.message.text.strip()
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        
        if user_input == "📥 Tải Video":
            await update.message.reply_text("📥 *Chế độ tải video*\n\nVui lòng gửi link video TikTok vào đây:", parse_mode='Markdown', reply_markup=current_keyboard)
            return
        elif user_input == "🖼️ Tải Ảnh":
            await update.message.reply_text("🖼️ *Chế độ tải ảnh*\n\nVui lòng gửi link bài đăng ảnh TikTok vào đây:", parse_mode='Markdown', reply_markup=current_keyboard)
            return
        elif user_input == "📦 Tải 100 Video từ Kênh":
            await update.message.reply_text("📦 *Tải 100 Video mới nhất từ kênh*\n\nVui lòng nhập username TikTok (không bao gồm @):\n\n⚠️ Quá trình tải có thể mất vài phút.", parse_mode='Markdown', reply_markup=current_keyboard)
            context.user_data['waiting_for_username'] = True
            return
        elif user_input == "📢 Broadcast" and self.is_admin(user_id):
            await self.broadcast_with_confirmation(update, context)
            return
        elif user_input == "📊 Thống kê" and self.is_admin(user_id):
            await self.stats_command(update, context)
            return
        elif user_input == "❓ Hướng dẫn":
            help_text = "📖 *Hướng dẫn sử dụng:*\n\n1️⃣ *Tải video:* Chọn '📥 Tải Video' và gửi link\n2️⃣ *Tải ảnh:* Chọn '🖼️ Tải Ảnh' và gửi link\n3️⃣ *Tải 100 video:* Chọn '📦 Tải 100 Video từ Kênh' và nhập username\n4️⃣ *Xóa keyboard:* Chọn '🗑️ Xóa Keyboard'"
            if self.is_admin(user_id):
                help_text += "\n\n👑 *Tính năng Admin:*\n• 📢 Broadcast tin nhắn\n• 📊 Xem thống kê bot"
            await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=current_keyboard)
            return
        elif user_input == "ℹ️ Thông tin Bot":
            info_text = f"ℹ️ *Thông tin Bot:*\n\n🤖 TikTok Downloader Bot v2.1\n✨ Tải video/ảnh không logo\n📦 Tải 100 video mới nhất\n👥 Tổng số người dùng: {len(self.users)}"
            await update.message.reply_text(info_text, parse_mode='Markdown', reply_markup=current_keyboard)
            return
        elif user_input == "🗑️ Xóa Keyboard":
            remove_keyboard = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("✅ Đã xóa keyboard. Gửi /start để hiện lại!", reply_markup=remove_keyboard)
            return
        
        if context.user_data.get('waiting_for_username'):
            username = user_input.replace('@', '')
            context.user_data['waiting_for_username'] = False
            await self.process_batch_download(update, username)
            return
        
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
            await update.message.reply_text("⚠️ Vui lòng sử dụng các nút bên dưới hoặc gửi link TikTok hợp lệ!", reply_markup=current_keyboard)
    
    async def process_batch_download(self, update: Update, username: str):
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
                await progress_msg.edit_text(f"📥 Đang tải video...\n📊 Tiến độ: {percent:.1f}% ({current}/{total})\n🎬 Đang tải: {title[:30]}...")
            downloaded_files = await self.download_batch_videos(videos, update_progress)
            if not downloaded_files:
                await progress_msg.edit_text("❌ Không thể tải video nào!")
                return
            await progress_msg.edit_text(f"📤 Đã tải xong {len(downloaded_files)}/{len(videos)} video. Đang gửi lên Telegram...")
            success_count = 0
            for filepath in downloaded_files:
                try:
                    with open(filepath, 'rb') as file:
                        await update.message.reply_video(video=file, caption=f"✅ Video {success_count + 1}/{len(downloaded_files)} từ @{username}", supports_streaming=True)
                    os.remove(filepath)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Lỗi gửi video: {e}")
                    continue
            await progress_msg.delete()
            current_keyboard = self.admin_keyboard if self.is_admin(update.effective_user.id) else self.main_keyboard
            await update.message.reply_text(f"✅ Hoàn thành!\n📊 Đã tải thành công: {success_count}/{len(downloaded_files)} video\n🎬 Từ kênh: @{username}", reply_markup=current_keyboard)
        except Exception as e:
            logger.error(f"Lỗi tải hàng loạt: {e}")
            await status_msg.edit_text(f"❌ Lỗi: {str(e)[:100]}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.add_user(user_id)
        welcome_msg = "🤖 *TikTok Downloader Bot*\n\n✨ *Chào mừng bạn!*\n\n📌 *Tính năng:*\n• ✅ Tải video TikTok *không logo*\n• ✅ Tải ảnh TikTok chất lượng cao\n• ✅ Tải 100 video mới nhất từ kênh\n• ✅ Xóa file ngay sau khi gửi\n\n💡 *Sử dụng các nút bên dưới để bắt đầu:*"
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=current_keyboard)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        help_text = "📖 *Hướng dẫn sử dụng:*\n\n1️⃣ *Tải video:* Chọn '📥 Tải Video' và gửi link\n2️⃣ *Tải ảnh:* Chọn '🖼️ Tải Ảnh' và gửi link\n3️⃣ *Tải 100 video:* Chọn '📦 Tải 100 Video từ Kênh' và nhập username\n4️⃣ *Xóa keyboard:* Chọn '🗑️ Xóa Keyboard'\n\n⚙️ *Các lệnh:*\n/start - Hiện keyboard\n/help - Hướng dẫn"
        if self.is_admin(user_id):
            help_text += "\n\n👑 *Lệnh Admin:*\n/broadcast - Gửi tin nhắn tới tất cả users\n/stats - Xem thống kê bot"
        current_keyboard = self.admin_keyboard if self.is_admin(user_id) else self.main_keyboard
        await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=current_keyboard)
    
    def run(self):
        application = Application.builder().token(self.token).build()
        self.application = application
        
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("broadcast", self.broadcast_with_confirmation))
        application.add_handler(CommandHandler("broadcast_caption", self.broadcast_with_photo))
        application.add_handler(CommandHandler("broadcast_video", self.broadcast_with_video))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CallbackQueryHandler(self.handle_broadcast_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        print("🚀 Bot đang chạy...")
        print(f"👥 Đã lưu {len(self.users)} users")
        if self.admin_id:
            print(f"👑 Admin ID: {self.admin_id}")
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    BOT_TOKEN = "8785070280:AAFVOnED_YtifSAoOWPS6Naesk44sKEOX2E"  # Thay bằng token của bạn
    ADMIN_ID = 5464983623  # Thay bằng ID Telegram của bạn
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Vui lòng cấu hình BOT_TOKEN!")
    else:
        print("🤖 Khởi động TikTok Downloader Bot...")
        bot = TikTokDownloaderBot(BOT_TOKEN, admin_id=ADMIN_ID)
        bot.run()
