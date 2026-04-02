# План исправления неработающей кнопки деталей тикета в Telegram

## Проблема
При нажатии на кнопку с задачей-обращением-тикетом в меню обращений ничего не происходит. Должно открываться меню с детальной информацией о тикете, с перепиской с модератором по шаблону как в оригинальном боте.

## Анализ
1. Кнопки тикетов создаются в `src/vtelemax/adapters/telegram/menu.py` функцией `build_user_tickets_pagination_keyboard` с `callback_data = f"{USER_TICKET_DETAILS_PREFIX}{ticket.ticket_id}"` (префикс `"user_ticket_"`).
2. Обработка префиксов тикетов реализована в `src/vtelemax/adapters/telegram/identity_adapter.py`:
   - Метод `handle_menu_action` проверяет `action_text.startswith(USER_TICKET_DETAILS_PREFIX)` и вызывает `_handle_view_ticket_details`.
   - Метод `_handle_view_ticket_details` формирует сообщение с деталями тикета и возвращает статус `"ticket_details"`.
3. В `src/vtelemax/adapters/telegram/router.py` отсутствует обработчик callback'ов с префиксами `USER_TICKET_DETAILS_PREFIX`, `USER_TICKETS_PREV_PAGE_PREFIX`, `USER_TICKETS_NEXT_PAGE_PREFIX`, `USER_TICKETS_PAGE_PREFIX`.
4. Импорт `USER_TICKET_DETAILS_PREFIX` также отсутствует в router.py.

## Решение
Добавить обработчик префиксов тикетов в router.py.

### Шаг 1: Добавить импорт USER_TICKET_DETAILS_PREFIX
В блоке импортов из `.menu` добавить `USER_TICKET_DETAILS_PREFIX` после `USER_TICKETS_NEXT_PAGE_PREFIX`.

**Точный diff:**
```diff
 from .menu import (
     NOTIFY_NO_CALLBACK,
     NOTIFY_YES_CALLBACK,
     RULES_ACCEPT_CALLBACK,
     USER_TICKETS_PAGE_PREFIX,
     USER_TICKETS_PREV_PAGE_PREFIX,
     USER_TICKETS_NEXT_PAGE_PREFIX,
+    USER_TICKET_DETAILS_PREFIX,
     BUTTON_BACK_TO_MAIN,
     BUTTON_BACK_TO_SUPPORT,
     BUTTON_DELIVERY,
     ...
 )
```

### Шаг 2: Добавить обработчик ticket_pagination_callback_handler
Разместить новый обработчик после `notifications_consent_callback_handler` (строка 632) и перед `main_menu_callback_handler` (строка 634).

**Код обработчика:**
```python
@router.callback_query(
    F.data.startswith(USER_TICKET_DETAILS_PREFIX) |
    F.data.startswith(USER_TICKETS_PREV_PAGE_PREFIX) |
    F.data.startswith(USER_TICKETS_NEXT_PAGE_PREFIX) |
    F.data.startswith(USER_TICKETS_PAGE_PREFIX)
)
async def ticket_pagination_callback_handler(callback: CallbackQuery) -> None:
    """Обработчик inline-кнопок деталей тикета и пагинации списка обращений."""

    event_logger = router_logger.bind(
        stage="ticket_pagination_callback",
        user_id=str(callback.from_user.id) if callback.from_user else "-",
    )
    await _try_process_pending_deliveries(callback.bot)

    if callback.from_user is None:
        event_logger.warning("Не удалось определить пользователя Telegram в callback пагинации тикетов.")
        await callback.answer("Не удалось определить пользователя. Повторите /start.", show_alert=True)
        return

    result = identity_adapter.handle_menu_action(
        telegram_user_id=callback.from_user.id,
        action_text=callback.data,
    )
    event_logger.info("Callback пагинации тикетов обработан. status={status}.", status=result.status)

    reply_markup = _choose_reply_markup(result)

    await callback.answer()
    if callback.message is not None:
        if not isinstance(reply_markup, InlineKeyboardMarkup):
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Inline-клавиатура уже очищена перед текстовым ответом.")
                else:
                    event_logger.debug("Не удалось убрать inline-клавиатуру перед отправкой текстового ответа.")
            await _answer_with_result(message=callback.message, result=result, reply_markup=reply_markup)
            return
        try:
            await callback.message.edit_text(
                result.message,
                parse_mode=result.parse_mode,
                reply_markup=reply_markup if isinstance(reply_markup, InlineKeyboardMarkup) else None,
            )
            return
        except Exception as error:  # noqa: BLE001
            if _is_message_not_modified_error(error):
                event_logger.debug("Редактирование callback-сообщения не требуется: контент не изменился.")
                return
            event_logger.debug("Не удалось перерисовать сообщение по callback, отправляем новое.")

    await _send_to_chat_with_result(
        bot=callback.bot,
        chat_id=callback.from_user.id,
        result=result,
        reply_markup=reply_markup,
    )
```

### Шаг 3: Проверить поддержку статусов в _choose_reply_markup
Убедиться, что функция `_choose_reply_markup` уже обрабатывает статусы:
- `"ticket_details"` и `"ticket_details_error"` → `back_to_support_keyboard` (строки 332-334)
- `"tickets_list"` с пагинацией → `build_user_tickets_pagination_keyboard` (строки 318-325)

Проверка показывает, что поддержка уже есть.

### Шаг 4: Тестирование
После внесения изменений необходимо запустить unit-тесты:
```bash
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_telegram_router.py
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_telegram_identity_adapter.py
```

### Шаг 5: Коммит
Создать коммит с сообщением на русском языке в повелительном наклонении, например:
```
Добавить обработчик callback'ов деталей тикета и пагинации в Telegram
```

## Риски
- Обработчик должен быть объявлен до `main_menu_callback_handler`, чтобы префиксы не перехватывались общим фильтром `F.data.in_(...)`.
- Необходимо убедиться, что `USER_TICKET_DETAILS_PREFIX` определён в `menu.py` (значение `"user_ticket_"`).
- Логика обработки виртуальных карт (`result.status == "virtual_card"`) в новом обработчике не требуется, так как префиксы тикетов не относятся к виртуальным картам.

## Проверка
После внесения изменений проверить:
1. Кнопка тикета в меню обращений открывает детали тикета.
2. Кнопки пагинации "Назад"/"Вперёд" работают.
3. Кнопка "Назад к списку обращений" возвращает к списку тикетов.
4. Ошибки (неверный ticket_id) обрабатываются корректно.