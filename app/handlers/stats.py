from aiogram import types
import logging
from peewee import fn
from models import Usage, User, db

logger = logging.getLogger(__name__)

async def handle_stats(message: types.Message):
    """Обработчик команды /stats"""
    logger.info(f"Received /stats command from user {message.from_user.id}")
    try:
        with db:
            total_duration = (
                Usage.select(fn.SUM(Usage.duration))
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .scalar()
                or 0
            )

            total_messages = (
                Usage.select()
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .count()
            )

            recent_usages = (
                Usage.select()
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .order_by(Usage.created_at.desc())
                .limit(5)
            )

            stats_message = (
                "📊 Ваша статистика использования:\n\n"
                f"🎯 Всего транскрибаций: {total_messages}\n"
                f"⏱ Общая длительность: {total_duration:.1f} сек.\n"
                f"⌛️ Среднее время: {(total_duration / total_messages if total_messages else 0):.1f} сек.\n"
            )

            if recent_usages:
                stats_message += "\n🔍 Последние транскрибации:\n"
                for usage in recent_usages:
                    chat_name = usage.chat.name or str(usage.chat.tg_chat_id)
                    chat_type = (
                        "личном чате"
                        if usage.chat.tg_chat_id == message.from_user.id
                        else f"группе {chat_name}"
                    )
                    stats_message += (
                        f"- {usage.created_at.strftime('%Y-%м-%d %H:%М:%С')} "
                        f"в {chat_type}: {usage.duration:.1f} сек.\n"
                    )

            await message.answer(stats_message)

    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при получении статистики.")