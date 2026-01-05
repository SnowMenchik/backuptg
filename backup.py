import os
import asyncio
import json
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("backup_errors.log", encoding='utf-8')]
)
logger = logging.getLogger(__name__)

class TelegramBackupBot:
    def __init__(self):
        self.api_id = None
        self.api_hash = None
        self.client = None
        self.session_file = "telegram_backup_session.session"
        self.output_folder = "backup"
        self.errors_file = os.path.join(self.output_folder, "errors.json")
        self.errors_list = []
        self.stats = {
            "text_messages": 0,
            "media_files": 0,
            "errors": 0,
            "processed": 0
        }
        
    def setup_folders(self):
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(os.path.join(self.output_folder, "media"), exist_ok=True)
    
    def safe_remove_session(self):
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
                print(f"Файл сессии удален: {self.session_file}")
            return True
        except Exception as e:
            print(f"Ошибка удаления сессии: {e}")
            return False
    
    def check_existing_session(self):
        print("\nПРОВЕРКА СЕССИИ")
        
        if os.path.exists(self.session_file):
            print(f"Найден файл сессии: {self.session_file}")
            
            choice = input("\n1 - Использовать сессию\n2 - Удалить и войти заново\nВыбор: ").strip()
            
            if choice == '1':
                return 'use_existing'
            else:
                if self.safe_remove_session():
                    return 'create_new'
                return 'exit'
        else:
            return 'create_new'
    
    async def initialize_client(self, session_action):
        if session_action == 'exit':
            return False
        
        print("\nИНИЦИАЛИЗАЦИЯ КЛИЕНТА")
        
        try:
            self.client = TelegramClient(
                "telegram_backup_session",
                self.api_id,
                self.api_hash,
                connection_retries=5,
                timeout=30
            )
            
            if session_action == 'use_existing':
                return await self.connect_with_existing_session()
            else:
                return await self.create_new_session()
                
        except Exception as e:
            print(f"Ошибка инициализации: {e}")
            return False
    
    async def connect_with_existing_session(self):
        try:
            print("Подключение с существующей сессией...")
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                print("Сессия устарела")
                choice = input("Удалить сессию? (y/n): ").lower().strip()
                if choice == 'y':
                    if self.safe_remove_session():
                        return await self.create_new_session()
                    return False
                return False
            
            print("Успешное подключение!")
            return True
            
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            return False
    
    async def create_new_session(self):
        print("\nНОВАЯ АВТОРИЗАЦИЯ")
        
        phone = input("Введите номер телефона: ").strip()
        
        try:
            if not self.client.is_connected():
                await self.client.connect()
            
            await self.client.send_code_request(phone)
            print("Код отправлен в Telegram!")
            
            for attempt in range(3):
                print(f"\nПопытка {attempt + 1}/3")
                code = input("Введите код из Telegram: ").strip()
                
                try:
                    await self.client.sign_in(phone, code)
                    print("Авторизация успешна!")
                    return True
                    
                except SessionPasswordNeededError:
                    password = input("Введите пароль 2FA: ")
                    await self.client.sign_in(password=password)
                    print("2FA пройдена!")
                    return True
                            
                except Exception as e:
                    error_msg = str(e)
                    if "PHONE_CODE_INVALID" in error_msg:
                        print("Неверный код")
                    elif "PHONE_CODE_EXPIRED" in error_msg:
                        print("Код истек")
                        await self.client.send_code_request(phone)
                        print("Новый код отправлен!")
                    else:
                        print(f"Ошибка: {e}")
                    
                    if attempt < 2:
                        print("Попробуйте еще раз")
                    else:
                        print("Превышено количество попыток")
                        return False
            
            return False
            
        except Exception as e:
            print(f"Ошибка авторизации: {e}")
            return False
    
    async def get_group_entity(self, chat_id: str):
        try:
            group_id = int(chat_id.strip())
            return await self.client.get_entity(group_id)
        except Exception as e:
            print(f"Ошибка получения группы: {e}")
            raise
    
    def save_error(self, message_id: int, error: str):
        error_data = {
            "message_id": message_id,
            "error": str(error),
            "timestamp": datetime.now().isoformat()
        }
        self.errors_list.append(error_data)
        self.stats["errors"] += 1
        
        try:
            with open(self.errors_file, 'a', encoding='utf-8') as f:
                json.dump(error_data, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"Ошибка сохранения ошибки: {e}")
    
    def save_message_to_json(self, message, dump_file):
        try:
            message_dict = message.to_dict()
            message_dict['_backup_info'] = {'exported_at': datetime.now().isoformat()}
            
            data = []
            if os.path.exists(dump_file):
                try:
                    with open(dump_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            data = json.loads(content)
                except json.JSONDecodeError:
                    data = []
            
            data.append(message_dict)
            
            with open(dump_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            self.stats["text_messages"] += 1
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
            self.save_error(message.id if hasattr(message, 'id') else 'unknown', e)
            return False
    
    async def download_media(self, message):
        media_folder = os.path.join(self.output_folder, "media")
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(media_folder, f"{message.id}_{timestamp}")
            
            downloaded_file = await self.client.download_media(
                message.media,
                file=filename
            )
            
            if downloaded_file:
                self.stats["media_files"] += 1
                return downloaded_file
        except Exception as e:
            logger.error(f"Ошибка скачивания медиа: {e}")
            self.save_error(message.id, e)
        return None
    
    async def export_messages(self, target_group_id: str, mode: int):
        print("\nНАЧИНАЕМ ЭКСПОРТ")
        
        try:
            group = await self.get_group_entity(target_group_id)
            print(f"Группа: {getattr(group, 'title', 'Неизвестно')}")
            print(f"ID: {group.id}")
        except Exception as e:
            print(f"Ошибка получения группы: {e}")
            return
        
        dump_file = os.path.join(self.output_folder, "dump.json")
        
        try:
            with open(self.errors_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
        except Exception:
            pass
        
        try:
            total_processed = 0
            
            while True:
                events = []
                
                async for event in self.client.iter_admin_log(group, limit=100, delete=True):
                    events.append(event)
                
                if not events:
                    print("Загрузка завершена")
                    break
                
                print(f"Загружено {len(events)} событий")
                
                for event in events:
                    try:
                        self.stats["processed"] += 1
                        total_processed += 1
                        
                        if not (event.deleted_message and event.old):
                            continue
                        
                        message = event.old
                        
                        if mode == 1:
                            self.save_message_to_json(message, dump_file)
                            if message.media:
                                await self.download_media(message)
                        
                        elif mode == 2 and message.media:
                            await self.download_media(message)
                        
                        elif mode == 3 and not message.media:
                            self.save_message_to_json(message, dump_file)
                        
                        if total_processed % 10 == 0:
                            print(f"Обработано: {total_processed}")
                        
                        await asyncio.sleep(0.1)
                        
                    except Exception as e:
                        message_id = getattr(event.old, 'id', 'unknown') if event.old else 'unknown'
                        logger.error(f"Ошибка обработки: {e}")
                        self.save_error(message_id, e)
                        continue
                
                await asyncio.sleep(2)
            
            print("\nСТАТИСТИКА")
            print(f"Обработано: {self.stats['processed']}")
            print(f"Текст: {self.stats['text_messages']}")
            print(f"Медиа: {self.stats['media_files']}")
            print(f"Ошибок: {self.stats['errors']}")
            
        except KeyboardInterrupt:
            print("\nЭкспорт прерван")
        except Exception as e:
            print(f"Критическая ошибка: {e}")
            logger.exception("Критическая ошибка")
    
    async def run(self):
        try:
            print("TELEGRAM BACKUP BOT")
            
            self.api_id = int(input("Введите api_id: "))
            self.api_hash = input("Введите api_hash: ")
            
            self.setup_folders()
            
            session_action = self.check_existing_session()
            
            client_initialized = await self.initialize_client(session_action)
            if not client_initialized:
                print("Не удалось инициализировать клиент")
                return
            
            print("\nПАРАМЕТРЫ ЭКСПОРТА")
            print("1 - Все сообщения")
            print("2 - Только медиа")
            print("3 - Только текст")
            
            export_mode = int(input("Выбор: "))
            
            if export_mode not in [1, 2, 3]:
                print("Неверный режим")
                return
            
            print("Введите ID группы (например: -1001234567890)")
            group_id = input("ID: ").strip()
            
            await self.export_messages(group_id, export_mode)
            
        except KeyboardInterrupt:
            print("\nПрограмма прервана")
        except Exception as e:
            print(f"Ошибка: {e}")
            logger.exception("Ошибка в основном цикле")
        finally:
            try:
                if self.client and self.client.is_connected():
                    await self.client.disconnect()
            except:
                pass
            
            print(f"\nДанные сохранены в папке: {self.output_folder}")

async def main():
    bot = TelegramBackupBot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nДо свидания!")
    input("\nНажмите Enter для выхода...")