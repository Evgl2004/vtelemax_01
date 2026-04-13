"""Константы и вспомогательные функции меню Telegram-адаптера."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_ABOUT,
    BUTTON_BACK_TO_MAIN,
    BUTTON_BACK_TO_SUPPORT,
    BUTTON_BALANCE,
    BUTTON_BUSINESS_LUNCH,
    BUTTON_DELIVERY,
    BUTTON_DOCS_LINK,
    BUTTON_HELP,
    BUTTON_MAIN_MENU,
    BUTTON_MY_TICKETS,
    BUTTON_NOTIFICATIONS_DOCS,
    BUTTON_NOTIFICATIONS_NO,
    BUTTON_NOTIFICATIONS_YES,
    BUTTON_PERSONAL_DATA_CONSENT_LINK,
    BUTTON_PRIVACY_POLICY_LINK,
    BUTTON_PROFILE,
    BUTTON_PROFILE_EDIT,
    BUTTON_PROFILE_EDIT_BIRTH_DATE,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_PROFILE_EDIT_EMAIL,
    BUTTON_PROFILE_EDIT_FIRST_NAME,
    BUTTON_PROFILE_EDIT_GENDER,
    BUTTON_PROFILE_EDIT_GENDER_FEMALE,
    BUTTON_PROFILE_EDIT_GENDER_MALE,
    BUTTON_PROFILE_EDIT_LAST_NAME,
    BUTTON_PROFILE_EDIT_NOTIFICATIONS,
    BUTTON_PROFILE_NOTIFICATIONS_ENABLE,
    BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_OFF,
    BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_ON,
    BUTTON_RETRY_IIKO_SYNC,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_SUPPORT_CONTACTS,
    BUTTON_SUPPORT_FEEDBACK,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_TABLE_BOOKING,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
    BUTTON_FEEDBACK_GRUZINKA,
    BUTTON_FEEDBACK_SUSAMI,
    BUTTON_FEEDBACK_CHINA,
    BUTTON_FEEDBACK_UZBECHKA,
    FEEDBACK_URL_GRUZINKA,
    FEEDBACK_URL_SUSAMI,
    FEEDBACK_URL_CHINA,
    FEEDBACK_URL_UZBECHKA,
    GuestMenuAction,
    MAILING_CONSENT_URLS,
    PERSONAL_DATA_CONSENT_URLS,
    OpenSupportTicketSummary,
    PersonSupportTicketSummary,
    PRIVACY_POLICY_URLS,
    build_business_lunch_screen,
    build_delivery_screen,
    build_table_booking_screen,
)

RULES_ACCEPT_CALLBACK = "rules_accept"
NOTIFY_YES_CALLBACK = "notify_yes"
NOTIFY_NO_CALLBACK = "notify_no"
USER_TICKETS_PAGE_PREFIX = "user_tickets_page_"
USER_TICKETS_PREV_PAGE_PREFIX = "user_tickets_prev_"
USER_TICKETS_NEXT_PAGE_PREFIX = "user_tickets_next_"
USER_TICKET_DETAILS_PREFIX = "user_ticket_"
USER_TICKET_REPLY_PREFIX = "ticket_reply_"
MOD_MAIN_CALLBACK = "mod_main"
MOD_LIST_PREFIX = "mod_list_"
MOD_PAGE_PREFIX = "mod_page_"
MOD_TICKET_PREFIX = "mod_ticket_"
MOD_REPLY_PREFIX = "mod_reply_"
MOD_OPEN_PREFIX = "mod_open_"
MOD_CLOSE_PREFIX = "mod_close_"
MOD_PHONE_SHOW_PREFIX = "mod_phone_show_"
MOD_PHONE_HIDE_PREFIX = "mod_phone_hide_"
GUEST_MESSAGE_CLOSE_CALLBACK = "guest_msg_close"
DOCS_URL = PERSONAL_DATA_CONSENT_URLS["telegram"]
NOTIFICATIONS_DOCS_URL = MAILING_CONSENT_URLS["telegram"]
SUPPORT_FEEDBACK_URL = "https://rdata.one/Nyyl"
SUPPORT_FEEDBACK_BUTTON_LABEL = "✍️ Оставить отзыв!"
_LOCAL_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")


def _to_local_datetime(value: datetime | None) -> datetime | None:
    """Конвертирует UTC-время в локальный часовой пояс интерфейса."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_LOCAL_TIMEZONE)


def _action_callback(action: GuestMenuAction) -> str:
    """Возвращает короткий callback-data по доменному действию меню."""

    return action.value


def build_contact_request_keyboard() -> ReplyKeyboardMarkup:
    """Создает клавиатуру с кнопкой отправки контакта."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=BUTTON_SEND_PHONE,
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_rules_consent_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру шага согласия с правилами."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_PERSONAL_DATA_CONSENT_LINK,
                    url=PERSONAL_DATA_CONSENT_URLS["telegram"],
                )
            ],
            [
                InlineKeyboardButton(
                    text=BUTTON_PRIVACY_POLICY_LINK,
                    url=PRIVACY_POLICY_URLS["telegram"],
                )
            ],
            [InlineKeyboardButton(text=BUTTON_ACCEPT_RULES, callback_data=RULES_ACCEPT_CALLBACK)],
        ]
    )


def build_notifications_consent_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру шага согласия на уведомления."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_DOCS, url=NOTIFICATIONS_DOCS_URL)],
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_YES, callback_data=NOTIFY_YES_CALLBACK)],
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_NO, callback_data=NOTIFY_NO_CALLBACK)],
        ]
    )


def build_iiko_sync_retry_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру повторной синхронизации с iiko."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_RETRY_IIKO_SYNC,
                    callback_data=_action_callback(GuestMenuAction.RETRY_IIKO_SYNC),
                )
            ],
        ]
    )


def build_main_menu_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру главного меню (группировка как в VK/MAX)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            # Строка 1: Баланс | Виртуальная карта
            [
                InlineKeyboardButton(text=BUTTON_BALANCE, callback_data=_action_callback(GuestMenuAction.BALANCE)),
                InlineKeyboardButton(text=BUTTON_VIRTUAL_CARD, callback_data=_action_callback(GuestMenuAction.VIRTUAL_CARD)),
            ],
            # Строка 2: Мне только спросить
            [InlineKeyboardButton(text=BUTTON_SUPPORT_QUESTION, callback_data=_action_callback(GuestMenuAction.SUPPORT_QUESTION))],
            # Строка 3: Оставить отзыв
            [InlineKeyboardButton(text=BUTTON_SUPPORT_FEEDBACK, callback_data=_action_callback(GuestMenuAction.SUPPORT_FEEDBACK))],
            # Строка 4: Бизнес-ланч | Бронь стола
            [
                InlineKeyboardButton(text=BUTTON_BUSINESS_LUNCH, callback_data=_action_callback(GuestMenuAction.BUSINESS_LUNCH)),
                InlineKeyboardButton(text=BUTTON_TABLE_BOOKING, callback_data=_action_callback(GuestMenuAction.TABLE_BOOKING)),
            ],
            # Строка 5: Доставка | Вакансии
            [
                InlineKeyboardButton(text=BUTTON_DELIVERY, callback_data=_action_callback(GuestMenuAction.DELIVERY)),
                InlineKeyboardButton(text=BUTTON_VACANCIES, callback_data=_action_callback(GuestMenuAction.VACANCIES)),
            ],
            # Строка 6: Профиль
            [InlineKeyboardButton(text=BUTTON_PROFILE, callback_data=_action_callback(GuestMenuAction.PROFILE))],
        ]
    )


def build_delivery_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру подменю «Доставка» с URL-кнопками заведений."""

    screen = build_delivery_screen()
    rows: list[list[InlineKeyboardButton]] = []
    for button in screen.buttons:
        if button.url is not None:
            rows.append([InlineKeyboardButton(text=button.label, url=button.url)])
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=button.label,
                        callback_data=_action_callback(button.action),
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_business_lunch_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру подменю «Бизнес-ланч» с URL-кнопками заведений."""

    screen = build_business_lunch_screen()
    rows: list[list[InlineKeyboardButton]] = []
    for button in screen.buttons:
        if button.url is not None:
            rows.append([InlineKeyboardButton(text=button.label, url=button.url)])
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=button.label,
                        callback_data=_action_callback(button.action),
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_table_booking_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру подменю «Бронь стола» с URL-кнопками заведений."""

    screen = build_table_booking_screen()
    rows: list[list[InlineKeyboardButton]] = []
    for button in screen.buttons:
        if button.url is not None:
            rows.append([InlineKeyboardButton(text=button.label, url=button.url)])
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=button.label,
                        callback_data=_action_callback(button.action),
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_support_menu_inline_keyboard(has_tickets: bool = False) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру подменю «Отдел заботы» (вертикальный список)."""

    buttons = [
        [InlineKeyboardButton(text=BUTTON_SUPPORT_FEEDBACK, callback_data=_action_callback(GuestMenuAction.SUPPORT_FEEDBACK))],
        [InlineKeyboardButton(text=BUTTON_SUPPORT_QUESTION, callback_data=_action_callback(GuestMenuAction.SUPPORT_QUESTION))],
    ]
    if has_tickets:
        buttons.append([InlineKeyboardButton(text=BUTTON_MY_TICKETS, callback_data=_action_callback(GuestMenuAction.MY_TICKETS))])
    buttons.extend(
        [
            [InlineKeyboardButton(text=BUTTON_SUPPORT_CONTACTS, callback_data=_action_callback(GuestMenuAction.SUPPORT_CONTACTS))],
            [InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=_action_callback(GuestMenuAction.BACK_TO_MAIN))],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_support_feedback_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру экрана «Оставить отзыв» с выбором заведения."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTON_FEEDBACK_GRUZINKA, url=FEEDBACK_URL_GRUZINKA)],
            [InlineKeyboardButton(text=BUTTON_FEEDBACK_SUSAMI, url=FEEDBACK_URL_SUSAMI)],
            [InlineKeyboardButton(text=BUTTON_FEEDBACK_CHINA, url=FEEDBACK_URL_CHINA)],
            [InlineKeyboardButton(text=BUTTON_FEEDBACK_UZBECHKA, url=FEEDBACK_URL_UZBECHKA)],
            [InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=_action_callback(GuestMenuAction.BACK_TO_MAIN))],
        ]
    )


def build_back_to_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой возврата в главное меню."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_BACK_TO_MAIN,
                    callback_data=_action_callback(GuestMenuAction.BACK_TO_MAIN),
                )
            ]
        ]
    )


def build_back_to_support_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой возврата в подменю отдела заботы."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_BACK_TO_SUPPORT,
                    callback_data=_action_callback(GuestMenuAction.BACK_TO_SUPPORT),
                )
            ]
        ]
    )


def build_back_to_tickets_list_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой возврата к списку обращений (MY_TICKETS)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_MY_TICKETS,
                    callback_data=_action_callback(GuestMenuAction.MY_TICKETS),
                )
            ]
        ]
    )


def build_ticket_details_inline_keyboard(*, ticket_id: str, can_reply: bool) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру карточки обращения гостя."""

    rows: list[list[InlineKeyboardButton]] = []
    if can_reply:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✍️ Ответить",
                    callback_data=f"{USER_TICKET_REPLY_PREFIX}{ticket_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=BUTTON_MY_TICKETS,
                callback_data=_action_callback(GuestMenuAction.MY_TICKETS),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_profile_inline_keyboard(*, notifications_allowed: bool) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру экрана профиля."""

    rows: list[list[InlineKeyboardButton]] = []
    if not notifications_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_NOTIFICATIONS_ENABLE,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE),
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT))],
            [InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=_action_callback(GuestMenuAction.BACK_TO_MAIN))],
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def build_profile_edit_inline_keyboard(*, can_edit_birth_date: bool) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру выбора редактируемого поля профиля."""

    rows = [
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_FIRST_NAME, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_FIRST_NAME))],
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_LAST_NAME, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_LAST_NAME))],
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_GENDER, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_GENDER))],
    ]
    if can_edit_birth_date:
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_BIRTH_DATE,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_BIRTH_DATE),
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_EMAIL, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_EMAIL))],
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_NOTIFICATIONS,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS),
                )
            ],
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_CANCEL, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_CANCEL))],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_profile_notifications_toggle_inline_keyboard(*, notifications_allowed: bool) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру отдельного подменю управления уведомлениями."""

    toggle_label = (
        BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_OFF
        if notifications_allowed
        else BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_ON
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_label,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE),
                )
            ],
        ]
    )


def build_profile_gender_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру выбора пола в режиме редактирования профиля."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_GENDER_MALE,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_GENDER_MALE),
                )
            ],
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_GENDER_FEMALE,
                    callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE),
                )
            ],
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_CANCEL, callback_data=_action_callback(GuestMenuAction.PROFILE_EDIT_CANCEL))],
        ]
    )


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Создает основную клавиатуру после успешной регистрации (вертикальный список)."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BUTTON_BALANCE)],
            [KeyboardButton(text=BUTTON_VIRTUAL_CARD)],
            [KeyboardButton(text=BUTTON_DELIVERY)],
            [KeyboardButton(text=BUTTON_SUPPORT_QUESTION)],
            [KeyboardButton(text=BUTTON_VACANCIES)],
            [KeyboardButton(text=BUTTON_SUPPORT_FEEDBACK)],
            [KeyboardButton(text=BUTTON_PROFILE)],
        ],
        resize_keyboard=True,
    )


def build_user_tickets_pagination_keyboard(
    current_page: int,
    total_pages: int,
    tickets: tuple[PersonSupportTicketSummary, ...] = (),
    has_tickets: bool = True,
) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру для пагинации списка тикетов пользователя."""
    
    buttons = []
    
    # Кнопки тикетов (если есть)
    for ticket in tickets:
        # Эмодзи статуса
        status_emoji = {
            "open": "🆕",
            "closed": "🔒",
        }.get(ticket.status.value, "❓")
        
        # Короткий идентификатор (последние 4 символа UUID в верхнем регистре)
        short_id = str(ticket.ticket_id)[-4:].upper()
        
        # Дата создания
        date_str = ""
        if ticket.created_at:
            date_str = ticket.created_at.strftime("%d.%m")
        
        # Текст кнопки
        label = f"{status_emoji} #{short_id}"
        if date_str:
            label += f" от {date_str}"
        
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"{USER_TICKET_DETAILS_PREFIX}{ticket.ticket_id}",
            )
        ])
    
    # Кнопка создания нового тикета (после списка тикетов)
    if has_tickets:
        buttons.append([
            InlineKeyboardButton(
                text="📝 Создать новый тикет",
                callback_data=_action_callback(GuestMenuAction.SUPPORT_QUESTION_FROM_LIST),
            )
        ])
    
    # Кнопки навигации (только если больше одной страницы)
    nav_buttons = []
    if total_pages > 1:
        if current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"{USER_TICKETS_PREV_PAGE_PREFIX}{current_page - 1}",
                )
            )
        
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"{current_page}/{total_pages}",
                callback_data="noop",  # Неактивная кнопка
            )
        )
        
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Вперед ▶️",
                    callback_data=f"{USER_TICKETS_NEXT_PAGE_PREFIX}{current_page + 1}",
                )
            )
    
    # Навигация (после кнопки создания)
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Кнопка возврата в главное меню
    buttons.append([
        InlineKeyboardButton(
            text=BUTTON_BACK_TO_MAIN,
            callback_data=_action_callback(GuestMenuAction.BACK_TO_MAIN),
        )
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_moderation_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает главное inline-меню модератора с фильтрами обращений."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🆕 Новые", callback_data=f"{MOD_LIST_PREFIX}new"),
                InlineKeyboardButton(text="🛠 В работе", callback_data=f"{MOD_LIST_PREFIX}work"),
            ],
            [
                InlineKeyboardButton(text="✅ Закрытые", callback_data=f"{MOD_LIST_PREFIX}closed"),
                InlineKeyboardButton(text="📚 Все", callback_data=f"{MOD_LIST_PREFIX}all"),
            ],
        ]
    )


def build_moderation_notification_inline_keyboard(ticket_id: str) -> InlineKeyboardMarkup:
    """Создает inline-кнопку быстрого ответа из уведомления модератору."""

    callback_data = f"{MOD_REPLY_PREFIX}{ticket_id}_new_1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=callback_data)],
        ]
    )


def build_moderation_reply_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-кнопку отмены при вводе ответа модератора."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=MOD_MAIN_CALLBACK)],
        ]
    )


def build_guest_message_close_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-кнопку закрытия входящего сообщения от модератора для гостя."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Закрыть", callback_data=GUEST_MESSAGE_CLOSE_CALLBACK)],
        ]
    )


def build_moderation_tickets_inline_keyboard(
    *,
    filter_key: str,
    current_page: int,
    total_pages: int,
    tickets: tuple[OpenSupportTicketSummary, ...],
) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру пагинации тикетов модератора."""

    buttons: list[list[InlineKeyboardButton]] = []

    status_emoji_map = {"open": "🆕", "in_progress": "🛠", "closed": "✅"}
    for ticket in tickets:
        status_value = ticket.status.value
        status_emoji = status_emoji_map.get(status_value, "❓")
        short_id = str(ticket.ticket_id)[-4:].upper()
        local_created_at = _to_local_datetime(ticket.created_at)
        date_text = local_created_at.strftime("%d.%m.%y") if local_created_at else ""
        phone_suffix = (ticket.guest_phone_suffix or "----").strip() or "----"
        label = f"{status_emoji} #{short_id}"
        if date_text:
            label = f"{label} от {date_text} - {phone_suffix}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"{MOD_TICKET_PREFIX}{ticket.ticket_id}_{filter_key}_{current_page}",
                )
            ]
        )

    if total_pages > 1:
        navigation_row: list[InlineKeyboardButton] = []
        if current_page > 1:
            navigation_row.append(
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"{MOD_PAGE_PREFIX}{filter_key}_{current_page - 1}",
                )
            )
        navigation_row.append(
            InlineKeyboardButton(
                text=f"{current_page}/{total_pages}",
                callback_data="noop",
            )
        )
        if current_page < total_pages:
            navigation_row.append(
                InlineKeyboardButton(
                    text="Вперед ▶️",
                    callback_data=f"{MOD_PAGE_PREFIX}{filter_key}_{current_page + 1}",
                )
            )
        buttons.append(navigation_row)

    buttons.append([InlineKeyboardButton(text="⬅️ К фильтрам", callback_data=MOD_MAIN_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_moderation_ticket_details_inline_keyboard(
    *,
    ticket_id: str,
    filter_key: str,
    page: int,
    status_value: str,
    show_phone: bool = False,
) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру карточки обращения модератора."""

    callback_suffix = f"{ticket_id}_{filter_key}_{page}"
    rows: list[list[InlineKeyboardButton]] = []
    if status_value != "closed":
        rows.append(
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"{MOD_REPLY_PREFIX}{callback_suffix}")]
        )
    if status_value == "closed":
        rows.append(
            [InlineKeyboardButton(text="🔓 Открыть", callback_data=f"{MOD_OPEN_PREFIX}{callback_suffix}")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"{MOD_CLOSE_PREFIX}{callback_suffix}")]
        )
    if show_phone:
        rows.append(
            [InlineKeyboardButton(text="🙈 Скрыть телефон", callback_data=f"{MOD_PHONE_HIDE_PREFIX}{callback_suffix}")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="📞 Телефон гостя", callback_data=f"{MOD_PHONE_SHOW_PREFIX}{callback_suffix}")]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К списку",
                callback_data=f"{MOD_PAGE_PREFIX}{filter_key}_{page}",
            ),
            InlineKeyboardButton(text="🏠 Меню", callback_data=MOD_MAIN_CALLBACK),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
