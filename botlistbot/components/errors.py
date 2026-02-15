async def no_library_support(update, context):
    chat_id = update.effective_chat.id
    text = "This feature will be available very soon."
    await context.bot.send_message(chat_id, text)
