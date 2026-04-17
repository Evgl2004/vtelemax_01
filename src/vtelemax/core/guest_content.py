"""Единый контент гостевых сценариев (эталон: Telegram-прототип).

В модуле хранятся:

1. тексты экранов;
2. подписи кнопок;
3. правила преобразования текстовой команды в доменное действие меню.
"""

from __future__ import annotations

from datetime import date, datetime

from .menu_contract import GuestMenuAction, MenuButtonContract, MenuScreenContract

BUTTON_BALANCE = "💰 Мой баланс"
BUTTON_VIRTUAL_CARD = "🪪 Карта"
BUTTON_DELIVERY = "🚚 Доставка"
BUTTON_SUPPORT = "🆘 Отдел заботы"
BUTTON_VACANCIES = "💼 Вакансии"

BUTTON_SUPPORT_FEEDBACK = "✍️ Оставить отзыв"
BUTTON_SUPPORT_FEEDBACK_LINK = "✍️ Оставить отзыв!"
BUTTON_SUPPORT_QUESTION = "❓ Мне только спросить"
BUTTON_SUPPORT_QUESTION_LEGACY = "❓ Мне только спросить (В разработке)"
BUTTON_MY_TICKETS = "📋 Мои обращения"
BUTTON_SUPPORT_CONTACTS = "📧 Контакты"
BUTTON_BACK_TO_MAIN = "🔙 Назад в меню"
BUTTON_BACK_TO_SUPPORT = "🔙 Назад в отдел заботы"

BUTTON_MAIN_MENU = "Главное меню"
BUTTON_PROFILE = "👤 Профиль"
BUTTON_PROFILE_EDIT = "✏️ Редактировать профиль"
BUTTON_PROFILE_EDIT_FIRST_NAME = "👤 Изменить имя"
BUTTON_PROFILE_EDIT_LAST_NAME = "👥 Изменить фамилию"
BUTTON_PROFILE_EDIT_GENDER = "⚥ Изменить пол"
BUTTON_PROFILE_EDIT_GENDER_MALE = "👨 Мужской"
BUTTON_PROFILE_EDIT_GENDER_FEMALE = "👩 Женский"
BUTTON_PROFILE_EDIT_BIRTH_DATE = "🎂 Указать дату рождения"
BUTTON_PROFILE_EDIT_EMAIL = "📧 Изменить email"
BUTTON_PROFILE_EDIT_NOTIFICATIONS = "🔔 Изменить уведомления"
BUTTON_PROFILE_EDIT_CANCEL = "🔙 Назад в профиль"
BUTTON_PROFILE_NOTIFICATIONS_ENABLE = "✅ Получать уведомления!"
BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_ON = "✅ Включить уведомления"
BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_OFF = "❌ Выключить уведомления"
BUTTON_HELP = "Помощь"
BUTTON_ABOUT = "О проекте"
BUTTON_SEND_PHONE = "📱 Поделиться контактом"
BUTTON_ACCEPT_RULES = "✅ Согласен"
BUTTON_DOCS_LINK = "📄 Открыть документы"
BUTTON_BONUSES = "💰 Бонусы"
BUTTON_NOTIFICATIONS_DOCS = "📄 Условия рассылки"
BUTTON_NOTIFICATIONS_YES = "✅ О да, кидай всё, что есть! 🔥"
BUTTON_NOTIFICATIONS_NO = "❌ Нет, останусь без подарков… 🙁"
BUTTON_RETRY_IIKO_SYNC = "🔄 Повторить синхронизацию"
FEEDBACK_FORM_URL = "https://rdata.one/Nyyl"
PERSONAL_DATA_CONSENT_URLS = {
    "telegram": "https://sagur.24vds.ru/personal-data-consent/tg/",
    "vk": "https://sagur.24vds.ru/personal-data-consent/vk/",
    "max": "https://sagur.24vds.ru/personal-data-consent/max/",
}
PRIVACY_POLICY_URLS = {
    "telegram": "https://sagur.24vds.ru/privacy-policy/tg/",
    "vk": "https://sagur.24vds.ru/privacy-policy/vk/",
    "max": "https://sagur.24vds.ru/privacy-policy/max/",
}
MAILING_CONSENT_URLS = {
    "telegram": "https://sagur.24vds.ru/mailing-consent/tg/",
    "vk": "https://sagur.24vds.ru/mailing-consent/vk/",
    "max": "https://sagur.24vds.ru/mailing-consent/max/",
}
BUTTON_PERSONAL_DATA_CONSENT_LINK = "📄 Согласие на ПД"
BUTTON_PRIVACY_POLICY_LINK = "📄 Политика конфиденциальности"
BUTTON_DELIVERY_GRUZINKA_NANI = "💃 Грузинка Нани"
BUTTON_DELIVERY_SUSAMI = "🍷 Сами Сусами"
BUTTON_DELIVERY_CHINA = "🍜 Чина"
BUTTON_DELIVERY_UZBECHKA = "☀️ Узбечка"
DELIVERY_URL_GRUZINKA_NANI = "https://gruzinka.rest.market/"
DELIVERY_URL_SUSAMI = "https://susami.rest.market/"
DELIVERY_URL_CHINA = "https://china.rest.market/"
DELIVERY_URL_UZBECHKA = "https://uzbechka.rest.market/"

# Кнопки и URL для бизнес-ланча
BUTTON_BUSINESS_LUNCH = "🍽️ Бизнес-ланч"
BUTTON_BUSINESS_LUNCH_GRUZINKA_NANI = "💃 Грузинка Нани"
BUTTON_BUSINESS_LUNCH_SUSAMI = "🍷 Сами Сусами"
BUTTON_BUSINESS_LUNCH_CHINA = "🍜 Чина"
BUTTON_BUSINESS_LUNCH_UZBECHKA = "☀️ Узбечка"
BUSINESS_LUNCH_URL_GRUZINKA_NANI = "https://rest-nani.ru/BL.jpg"
BUSINESS_LUNCH_URL_SUSAMI = "https://rest-susami.ru/BL.jpg"
BUSINESS_LUNCH_URL_CHINA = "https://rest-china.ru/BL.jpg"
BUSINESS_LUNCH_URL_UZBECHKA = "https://rest-uzbechka.ru/BL.jpg"

# Кнопки и URL для бронирования столиков
BUTTON_TABLE_BOOKING = "🪑 Бронь стола"
BUTTON_TABLE_BOOKING_GRUZINKA_NANI = "💃 Грузинка Нани"
BUTTON_TABLE_BOOKING_SUSAMI = "🍷 Сами Сусами"
BUTTON_TABLE_BOOKING_CHINA = "🍜 Чина"
BUTTON_TABLE_BOOKING_UZBECHKA = "☀️ Узбечка"
TABLE_BOOKING_URL_GRUZINKA_NANI = "https://gruzinka.restoplace.ws/"
TABLE_BOOKING_URL_SUSAMI = "https://susami.restoplace.ws/"
TABLE_BOOKING_URL_CHINA = "https://china.restoplace.ws/"
TABLE_BOOKING_URL_UZBECHKA = "https://usbechka.restoplace.ws/"

# Кнопки и URL для отзывов по заведениям
BUTTON_FEEDBACK_GRUZINKA = "💃 Грузинка"
BUTTON_FEEDBACK_SUSAMI = "🍷 Сами Сусами"
BUTTON_FEEDBACK_CHINA = "🍜 Чина"
BUTTON_FEEDBACK_UZBECHKA = "☀️ Узбечка"
FEEDBACK_URL_GRUZINKA = "https://rdata.one/nwKl"
FEEDBACK_URL_SUSAMI = "https://rdata.one/pwKl"
FEEDBACK_URL_CHINA = "https://rdata.one/xxKl"
FEEDBACK_URL_UZBECHKA = "https://rdata.one/vxKl"


CONTACT_SCREEN_TEXTS = {
    "telegram": (
        "📱 Чтобы подключиться к программе лояльности, нажмите кнопку «📱 Поделиться контактом».\n"
        "После отправки контакта мы продолжим регистрацию."
    ),
    "vk": (
        "📱 Чтобы подключиться к программе лояльности, отправьте номер телефона "
        "текстом в формате +79991234567."
    ),
    "max": (
        "📱 Чтобы подключиться к программе лояльности, нажмите кнопку «📱 Поделиться контактом».\n"
        "После отправки контакта мы продолжим регистрацию."
    ),
}


def normalize_menu_text(raw_text: str) -> str:
    """Нормализует пользовательский текст для распознавания действия меню."""

    return " ".join((raw_text or "").strip().split()).lower()


def resolve_guest_menu_action(raw_text: str) -> GuestMenuAction | None:
    """Определяет действие гостевого меню по тексту/команде."""

    normalized = normalize_menu_text(raw_text)
    if not normalized:
        return None

    mapping: dict[str, GuestMenuAction] = {
        BUTTON_MAIN_MENU.lower(): GuestMenuAction.MAIN_MENU,
        BUTTON_PROFILE.lower(): GuestMenuAction.PROFILE,
        BUTTON_PROFILE_EDIT.lower(): GuestMenuAction.PROFILE_EDIT,
        BUTTON_PROFILE_EDIT_FIRST_NAME.lower(): GuestMenuAction.PROFILE_EDIT_FIRST_NAME,
        BUTTON_PROFILE_EDIT_LAST_NAME.lower(): GuestMenuAction.PROFILE_EDIT_LAST_NAME,
        BUTTON_PROFILE_EDIT_GENDER.lower(): GuestMenuAction.PROFILE_EDIT_GENDER,
        BUTTON_PROFILE_EDIT_GENDER_MALE.lower(): GuestMenuAction.PROFILE_EDIT_GENDER_MALE,
        BUTTON_PROFILE_EDIT_GENDER_FEMALE.lower(): GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE,
        BUTTON_PROFILE_EDIT_BIRTH_DATE.lower(): GuestMenuAction.PROFILE_EDIT_BIRTH_DATE,
        BUTTON_PROFILE_EDIT_EMAIL.lower(): GuestMenuAction.PROFILE_EDIT_EMAIL,
        BUTTON_PROFILE_EDIT_NOTIFICATIONS.lower(): GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS,
        BUTTON_PROFILE_EDIT_CANCEL.lower(): GuestMenuAction.PROFILE_EDIT_CANCEL,
        BUTTON_PROFILE_NOTIFICATIONS_ENABLE.lower(): GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE,
        BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_ON.lower(): GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE,
        BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_OFF.lower(): GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE,
        BUTTON_HELP.lower(): GuestMenuAction.HELP,
        "/help": GuestMenuAction.HELP,
        BUTTON_ABOUT.lower(): GuestMenuAction.ABOUT,
        BUTTON_SEND_PHONE.lower(): GuestMenuAction.SHARE_CONTACT,
        BUTTON_BALANCE.lower(): GuestMenuAction.BALANCE,
        BUTTON_BONUSES.lower(): GuestMenuAction.BALANCE,
        BUTTON_VIRTUAL_CARD.lower(): GuestMenuAction.VIRTUAL_CARD,
        BUTTON_DELIVERY.lower(): GuestMenuAction.DELIVERY,
        BUTTON_BUSINESS_LUNCH.lower(): GuestMenuAction.BUSINESS_LUNCH,
        BUTTON_TABLE_BOOKING.lower(): GuestMenuAction.TABLE_BOOKING,
        BUTTON_SUPPORT.lower(): GuestMenuAction.SUPPORT,
        BUTTON_VACANCIES.lower(): GuestMenuAction.VACANCIES,
        BUTTON_SUPPORT_FEEDBACK.lower(): GuestMenuAction.SUPPORT_FEEDBACK,
        BUTTON_SUPPORT_QUESTION.lower(): GuestMenuAction.SUPPORT_QUESTION,
        BUTTON_SUPPORT_QUESTION_LEGACY.lower(): GuestMenuAction.SUPPORT_QUESTION,
        "support_question_from_list": GuestMenuAction.SUPPORT_QUESTION_FROM_LIST,
        BUTTON_MY_TICKETS.lower(): GuestMenuAction.MY_TICKETS,
        BUTTON_SUPPORT_CONTACTS.lower(): GuestMenuAction.SUPPORT_CONTACTS,
        BUTTON_BACK_TO_MAIN.lower(): GuestMenuAction.BACK_TO_MAIN,
        BUTTON_BACK_TO_SUPPORT.lower(): GuestMenuAction.BACK_TO_SUPPORT,
        BUTTON_DOCS_LINK.lower(): GuestMenuAction.OPEN_DOCS,
        BUTTON_PERSONAL_DATA_CONSENT_LINK.lower(): GuestMenuAction.OPEN_DOCS,
        BUTTON_PRIVACY_POLICY_LINK.lower(): GuestMenuAction.OPEN_DOCS,
        BUTTON_ACCEPT_RULES.lower(): GuestMenuAction.ACCEPT_RULES,
        BUTTON_NOTIFICATIONS_YES.lower(): GuestMenuAction.NOTIFY_YES,
        BUTTON_NOTIFICATIONS_NO.lower(): GuestMenuAction.NOTIFY_NO,
        BUTTON_RETRY_IIKO_SYNC.lower(): GuestMenuAction.RETRY_IIKO_SYNC,
    }
    action = mapping.get(normalized)
    if action is not None:
        return action
    try:
        return GuestMenuAction(normalized)
    except ValueError:
        return None


def build_start_rules_screen(platform: str = "telegram") -> MenuScreenContract:
    """Экран приветствия гостя с запросом согласия (эталонный текст)."""

    return MenuScreenContract(
        screen_id="start_rules",
        text=(
            "👋 Здравствуй Друг!\n\n"
            "Добро пожаловать к нам в гости!\n\n"
            "📜 Для начала нам необходимо получить твоё согласие на обработку персональных данных "
            "и согласие с политикой конфиденциальности.\n\n"
            "👉 Прошу ознакомиться с документами по ссылкам ниже и нажать кнопку «✅ Согласен»."
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_PERSONAL_DATA_CONSENT_LINK,
                url=PERSONAL_DATA_CONSENT_URLS[platform],
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_PRIVACY_POLICY_LINK,
                url=PRIVACY_POLICY_URLS[platform],
            ),
            MenuButtonContract(action=GuestMenuAction.ACCEPT_RULES, label=BUTTON_ACCEPT_RULES),
        ),
    )


def build_start_contact_screen(platform: str = "telegram") -> MenuScreenContract:
    """Экран запроса номера телефона (эталонный текст)."""

    text = CONTACT_SCREEN_TEXTS.get(platform, CONTACT_SCREEN_TEXTS["telegram"])
    buttons: tuple[MenuButtonContract, ...]
    if platform in {"telegram", "max"}:
        buttons = (MenuButtonContract(action=GuestMenuAction.SHARE_CONTACT, label=BUTTON_SEND_PHONE),)
    else:
        buttons = ()
    return MenuScreenContract(
        screen_id="start_contact",
        text=text,
        buttons=buttons,
    )


def build_first_name_input_screen() -> MenuScreenContract:
    """Экран запроса имени в сокращенной регистрации."""

    return MenuScreenContract(
        screen_id="first_name_input",
        text=(
            "👤 Отлично, номер сохранен.\n\n"
            "Теперь напишите ваше имя текстовым сообщением."
        ),
    )


def build_notifications_consent_screen(
    profile_text: str | None = None,
    platform: str = "telegram",
) -> MenuScreenContract:
    """Экран обязательного выбора по уведомлениям.

    Параметр `profile_text` оставлен для обратной совместимости:
    - если передан, выводится перед блоком согласия;
    - в актуальном UX-flow блок уведомлений можно показывать отдельно.
    """

    notification_text = (
        "📣 Мы хотим радовать вас персональными предложениями и акциями.\n"
        "Ознакомьтесь с условиями получения уведомлений по ссылке ниже и сделайте выбор:"
    )
    full_text = notification_text if not profile_text else f"{profile_text}\n\n{notification_text}"
    return MenuScreenContract(
        screen_id="notifications_consent",
        text=full_text,
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_NOTIFICATIONS_DOCS,
                url=MAILING_CONSENT_URLS[platform],
            ),
            MenuButtonContract(action=GuestMenuAction.NOTIFY_YES, label=BUTTON_NOTIFICATIONS_YES),
            MenuButtonContract(action=GuestMenuAction.NOTIFY_NO, label=BUTTON_NOTIFICATIONS_NO),
        ),
    )


def build_virtual_card_result_screen() -> MenuScreenContract:
    """Экран-подтверждение после отправки QR-кодов виртуальной карты."""

    return MenuScreenContract(
        screen_id="virtual_card_result",
        text=(
            "🪪 Список виртуальных карт и QR-коды отправлены выше.\n\n"
            "Нажмите «🔙 Назад в меню», чтобы вернуться к разделам."
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),),
    )


def build_legacy_upgrade_screen(platform: str = "telegram") -> MenuScreenContract:
    """Экран запуска обновления для legacy-пользователя.

    Сценарий intentionally пересекается с обычной регистрации:
    на первом этапе мы также запрашиваем подтверждение номера телефона.
    """
    if platform == "vk":
        return MenuScreenContract(
            screen_id="legacy_upgrade",
            text=(
                "🔄 Мы обнаружили профиль из предыдущей версии бота.\n\n"
                "Чтобы обновить данные и продолжить работу, отправьте номер телефона "
                "текстом в формате +79991234567."
            ),
            buttons=(),
        )
    return MenuScreenContract(
        screen_id="legacy_upgrade",
        text=(
            "🔄 Мы обнаружили профиль из предыдущей версии бота.\n\n"
            "Чтобы обновить данные и продолжить работу, подтвердите ваш номер телефона "
            "через кнопку «Отправить номер телефона»."
        ),
        buttons=(
            MenuButtonContract(action=GuestMenuAction.SHARE_CONTACT, label=BUTTON_SEND_PHONE),
        ),
    )


def build_main_menu_screen(user_name: str = "Гость") -> MenuScreenContract:
    """Главное меню гостя после регистрации."""

    return MenuScreenContract(
        screen_id="main_menu",
        text=(
            f"👋 {user_name}, добро пожаловать!\n"
            "Вы в главном меню.\n"
            "Выберите раздел:"
        ),
        buttons=(
            MenuButtonContract(action=GuestMenuAction.BALANCE, label=BUTTON_BALANCE),
            MenuButtonContract(action=GuestMenuAction.VIRTUAL_CARD, label=BUTTON_VIRTUAL_CARD),
            MenuButtonContract(action=GuestMenuAction.DELIVERY, label=BUTTON_DELIVERY),
            MenuButtonContract(action=GuestMenuAction.SUPPORT_QUESTION, label=BUTTON_SUPPORT_QUESTION),
            MenuButtonContract(action=GuestMenuAction.VACANCIES, label=BUTTON_VACANCIES),
            MenuButtonContract(
                action=GuestMenuAction.SUPPORT_FEEDBACK,
                label=BUTTON_SUPPORT_FEEDBACK,
            ),
            MenuButtonContract(action=GuestMenuAction.BUSINESS_LUNCH, label=BUTTON_BUSINESS_LUNCH),
            MenuButtonContract(action=GuestMenuAction.TABLE_BOOKING, label=BUTTON_TABLE_BOOKING),
            MenuButtonContract(action=GuestMenuAction.PROFILE, label=BUTTON_PROFILE),
        ),
    )


def build_delivery_screen() -> MenuScreenContract:
    """Экран подменю «Доставка» с ссылками на страницы заведений."""

    return MenuScreenContract(
        screen_id="delivery",
        text=(
            "🚚 Доставка\n\n"
            "Выберите заведение:"
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_DELIVERY_GRUZINKA_NANI,
                url=DELIVERY_URL_GRUZINKA_NANI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_DELIVERY_SUSAMI,
                url=DELIVERY_URL_SUSAMI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_DELIVERY_CHINA,
                url=DELIVERY_URL_CHINA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_DELIVERY_UZBECHKA,
                url=DELIVERY_URL_UZBECHKA,
            ),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
    )


def build_business_lunch_screen() -> MenuScreenContract:
    """Экран подменю «Бизнес-ланч» со ссылками на изображения бизнес-ланча."""

    return MenuScreenContract(
        screen_id="business_lunch",
        text=(
            "🍽️ Бизнес-ланч\n\n"
            "Выберите заведение для просмотра бизнес-ланча:"
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_BUSINESS_LUNCH_GRUZINKA_NANI,
                url=BUSINESS_LUNCH_URL_GRUZINKA_NANI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_BUSINESS_LUNCH_SUSAMI,
                url=BUSINESS_LUNCH_URL_SUSAMI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_BUSINESS_LUNCH_CHINA,
                url=BUSINESS_LUNCH_URL_CHINA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_BUSINESS_LUNCH_UZBECHKA,
                url=BUSINESS_LUNCH_URL_UZBECHKA,
            ),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
    )


def build_table_booking_screen() -> MenuScreenContract:
    """Экран подменю «Бронь стола» со ссылками на страницы бронирования."""

    return MenuScreenContract(
        screen_id="table_booking",
        text=(
            "🪑 Бронь стола\n\n"
            "Выберите заведение для бронирования столика онлайн:"
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_TABLE_BOOKING_GRUZINKA_NANI,
                url=TABLE_BOOKING_URL_GRUZINKA_NANI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_TABLE_BOOKING_SUSAMI,
                url=TABLE_BOOKING_URL_SUSAMI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_TABLE_BOOKING_CHINA,
                url=TABLE_BOOKING_URL_CHINA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_TABLE_BOOKING_UZBECHKA,
                url=TABLE_BOOKING_URL_UZBECHKA,
            ),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
    )


def build_feedback_venues_screen() -> MenuScreenContract:
    """Экран подменю «Оставить отзыв» со ссылками на страницы отзывов заведений."""

    return MenuScreenContract(
        screen_id="feedback_venues",
        text=(
            "✍️ Оставить отзыв\n\n"
            "Выберите заведение:"
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_GRUZINKA,
                url=FEEDBACK_URL_GRUZINKA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_SUSAMI,
                url=FEEDBACK_URL_SUSAMI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_CHINA,
                url=FEEDBACK_URL_CHINA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_UZBECHKA,
                url=FEEDBACK_URL_UZBECHKA,
            ),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
        parse_mode="plain",
    )


def build_support_menu_screen(has_tickets: bool) -> MenuScreenContract:
    """Экран раздела поддержки."""

    buttons: list[MenuButtonContract] = [
        MenuButtonContract(action=GuestMenuAction.SUPPORT_FEEDBACK, label=BUTTON_SUPPORT_FEEDBACK),
        MenuButtonContract(action=GuestMenuAction.SUPPORT_QUESTION, label=BUTTON_SUPPORT_QUESTION),
    ]
    if has_tickets:
        buttons.append(MenuButtonContract(action=GuestMenuAction.MY_TICKETS, label=BUTTON_MY_TICKETS))
    buttons.extend(
        [
            MenuButtonContract(action=GuestMenuAction.SUPPORT_CONTACTS, label=BUTTON_SUPPORT_CONTACTS),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ]
    )
    return MenuScreenContract(
        screen_id="support_menu",
        text="🆘 *Отдел заботы*\n\nВыберите действие:",
        buttons=tuple(buttons),
        parse_mode="markdown",
    )


def build_balance_screen(balance: float) -> MenuScreenContract:
    """Экран бонусного баланса (эталонная структура текста)."""

    return MenuScreenContract(
        screen_id="balance",
        text=(
            "💰 *Ваш бонусный баланс*\n\n"
            f"Текущие бонусы: {balance:.2f}\n"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),),
        parse_mode="markdown",
    )


def build_vacancies_screen() -> MenuScreenContract:
    """Экран раздела вакансий (эталонный текст)."""

    return MenuScreenContract(
        screen_id="vacancies",
        text=(
            "💼 *Вакансии*\n\n"
            "Ждем классных, ответственных, позитивных, энергичных и профессиональных "
            "сотрудников в дружные команды наших заведений!\n\n"
            "Гарантируем:\n"
            "• крепкие коллективы, в которых весело работать и приятно отдыхать после смены\n"
            "• с нами – непрерывное профессиональное развитие\n"
            "• мы не дадим скучать и хандрить\n"
            "• достойный доход и щедрые чаевые\n\n"
            "Если чувствуешь, что хочешь работать в заведениях самого уютного и надёжного "
            "бренда Тюмени – переходи по ссылке и оставляй заявку!\n\n"
            "👉 https://team.sobolevalliance.su/vacancy"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),),
        parse_mode="markdown",
    )


def build_support_feedback_screen() -> MenuScreenContract:
    """Экран раздела «Оставить отзыв» (теперь с выбором заведения)."""

    return MenuScreenContract(
        screen_id="support_feedback",
        text=(
            "✍️ Оставить отзыв\n\n"
            "Выберите заведение:"
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_GRUZINKA,
                url=FEEDBACK_URL_GRUZINKA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_SUSAMI,
                url=FEEDBACK_URL_SUSAMI,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_CHINA,
                url=FEEDBACK_URL_CHINA,
            ),
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_FEEDBACK_UZBECHKA,
                url=FEEDBACK_URL_UZBECHKA,
            ),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
        parse_mode="plain",
    )


def build_iiko_sync_retry_screen() -> MenuScreenContract:
    """Экран повторной синхронизации с iiko при временной ошибке."""

    return MenuScreenContract(
        screen_id="iiko_sync_retry",
        text=(
            "⚠️ Не удалось завершить синхронизацию с бонусной системой iiko.\n\n"
            "Это может быть временная проблема связи. Пожалуйста, нажмите кнопку ниже "
            "через несколько секунд."
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.RETRY_IIKO_SYNC,
                label=BUTTON_RETRY_IIKO_SYNC,
            ),
        ),
    )


def build_iiko_sync_pending_screen() -> MenuScreenContract:
    """Экран промежуточного шага синхронизации с iiko."""

    return MenuScreenContract(
        screen_id="iiko_sync_pending",
        text=(
            "⏳ Сохраняем ваши данные в бонусной системе iiko.\n\n"
            "Пожалуйста, подождите несколько секунд. "
            "Если связь нестабильна, мы предложим повторить синхронизацию."
        ),
    )


def build_support_question_screen() -> MenuScreenContract:
    """Экран начала сценария обращения в поддержку."""

    return MenuScreenContract(
        screen_id="support_question",
        text=(
            "❓ *Мне только спросить*\n\n"
            "Пожалуйста, отправьте ваш вопрос, и наш модератор свяжется с вами в ближайшее время.\n\n"
            "Минимальная длина обращения: 10 символов.\n\n"
            "Введите ваш вопрос:"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),),
        parse_mode="markdown",
    )


def build_support_question_confirmation_screen() -> MenuScreenContract:
    """Экран подтверждения создания тикета (после отправки вопроса)."""

    return MenuScreenContract(
        screen_id="support_question_confirmation",
        text=(
            "📨 *Ваш вопрос принят!*\n\n"
            "Модератор рассмотрит обращение в ближайшее время."
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),),
        parse_mode="markdown",
    )


def build_support_contacts_screen() -> MenuScreenContract:
    """Экран контактной информации."""

    return MenuScreenContract(
        screen_id="support_contacts",
        text=(
            "📧 Контакты:\n\n"
            "Почта для связи: info@sobolev.rest\n"
            "Сайт: https://sobolevalliance.su\n"
            "Соцсети: @sobolevalliance"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_SUPPORT, label=BUTTON_BACK_TO_SUPPORT),),
    )


def build_help_screen() -> MenuScreenContract:
    """Экран помощи для гостя."""

    return MenuScreenContract(
        screen_id="help",
        text=(
            "ℹ️ Помощь по боту\n\n"
            "• /start или «Начать» — запуск и регистрация\n"
            "• /help или «Помощь» — показать эту подсказку\n"
            "• Для связи с поддержкой используйте пункт меню «❓ Мне только спросить»"
        ),
    )


def build_about_screen() -> MenuScreenContract:
    """Экран «О проекте»."""

    return MenuScreenContract(
        screen_id="about",
        text=(
            "vtelemax — единая платформа для Telegram, VK и MAX с общей строгой "
            "идентификацией пользователей по телефону."
        ),
    )


def build_profile_not_found_screen() -> MenuScreenContract:
    """Экран, когда профиль еще не зарегистрирован."""

    return MenuScreenContract(
        screen_id="profile_not_found",
        text=(
            "Профиль пока не найден. Сначала отправьте свой номер телефона "
            "через кнопку контакта."
        ),
        buttons=(
            MenuButtonContract(action=GuestMenuAction.SHARE_CONTACT, label=BUTTON_SEND_PHONE),
        ),
    )


def build_profile_screen(
    phone_e164: str,
    accounts_count: int,
    accounts_platforms: tuple[str, ...] | None = None,
    *,
    first_name_input: str | None = None,
    last_name_input: str | None = None,
    gender: str | None = None,
    birth_date: date | None = None,
    email: str | None = None,
    rules_accepted: bool = False,
    rules_accepted_at: datetime | None = None,
    notifications_allowed: bool | None = None,
    notifications_allowed_at: datetime | None = None,
) -> MenuScreenContract:
    """Экран профиля зарегистрированного пользователя в формате review-анкеты."""

    buttons: list[MenuButtonContract] = []
    if not notifications_allowed:
        buttons.append(
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE,
                label=BUTTON_PROFILE_NOTIFICATIONS_ENABLE,
            )
        )
    buttons.extend(
        [
            MenuButtonContract(action=GuestMenuAction.PROFILE_EDIT, label=BUTTON_PROFILE_EDIT),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ]
    )

    return MenuScreenContract(
        screen_id="profile",
        text=build_profile_review_text(
            phone_e164=phone_e164,
            accounts_count=accounts_count,
            accounts_platforms=accounts_platforms,
            first_name_input=first_name_input,
            last_name_input=last_name_input,
            gender=gender,
            birth_date=birth_date,
            email=email,
            rules_accepted=rules_accepted,
            rules_accepted_at=rules_accepted_at,
            notifications_allowed=notifications_allowed,
            notifications_allowed_at=notifications_allowed_at,
        ),
        buttons=tuple(buttons),
        parse_mode="markdown",
    )


def build_profile_edit_screen(*, can_edit_birth_date: bool) -> MenuScreenContract:
    """Экран выбора поля для редактирования профиля."""

    buttons: list[MenuButtonContract] = [
        MenuButtonContract(
            action=GuestMenuAction.PROFILE_EDIT_FIRST_NAME,
            label=BUTTON_PROFILE_EDIT_FIRST_NAME,
        ),
        MenuButtonContract(
            action=GuestMenuAction.PROFILE_EDIT_LAST_NAME,
            label=BUTTON_PROFILE_EDIT_LAST_NAME,
        ),
        MenuButtonContract(
            action=GuestMenuAction.PROFILE_EDIT_GENDER,
            label=BUTTON_PROFILE_EDIT_GENDER,
        ),
    ]
    if can_edit_birth_date:
        buttons.append(
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_BIRTH_DATE,
                label=BUTTON_PROFILE_EDIT_BIRTH_DATE,
            )
        )
    buttons.extend(
        [
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_EMAIL,
                label=BUTTON_PROFILE_EDIT_EMAIL,
            ),
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS,
                label=BUTTON_PROFILE_EDIT_NOTIFICATIONS,
            ),
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_CANCEL,
                label=BUTTON_PROFILE_EDIT_CANCEL,
            ),
        ]
    )
    birth_hint = (
        "Дата рождения уже заполнена и по правилам может быть указана только один раз."
        if not can_edit_birth_date
        else "Дату рождения можно указать один раз, если она еще не заполнена."
    )
    return MenuScreenContract(
        screen_id="profile_edit",
        text=(
            "✏️ *Редактирование профиля*\n\n"
            "Выберите поле, которое хотите изменить.\n"
            "Телефон изменять нельзя.\n\n"
            f"ℹ️ {birth_hint}"
        ),
        buttons=tuple(buttons),
        parse_mode="markdown",
    )


def build_profile_gender_screen() -> MenuScreenContract:
    """Экран выбора пола в режиме редактирования профиля."""

    return MenuScreenContract(
        screen_id="profile_edit_gender",
        text="⚥ Выберите пол:",
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_GENDER_MALE,
                label=BUTTON_PROFILE_EDIT_GENDER_MALE,
            ),
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE,
                label=BUTTON_PROFILE_EDIT_GENDER_FEMALE,
            ),
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_CANCEL,
                label=BUTTON_PROFILE_EDIT_CANCEL,
            ),
        ),
    )


def build_profile_notifications_edit_screen(*, notifications_allowed: bool) -> MenuScreenContract:
    """Экран включения/выключения уведомлений в режиме редактирования профиля."""

    toggle_label = (
        BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_OFF
        if notifications_allowed
        else BUTTON_PROFILE_NOTIFICATIONS_TOGGLE_ON
    )
    current_status = "Активны ✅" if notifications_allowed else "Отказ ❌"
    return MenuScreenContract(
        screen_id="profile_edit_notifications",
        text=(
            "🔔 *Уведомления*\n\n"
            f"Текущий статус: {current_status}\n\n"
            "Нажмите кнопку ниже, чтобы изменить статус уведомлений."
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE,
                label=toggle_label,
            ),
            MenuButtonContract(
                action=GuestMenuAction.PROFILE_EDIT_CANCEL,
                label=BUTTON_PROFILE_EDIT_CANCEL,
            ),
        ),
        parse_mode="markdown",
    )


def build_profile_review_text(
    *,
    phone_e164: str,
    accounts_count: int,
    accounts_platforms: tuple[str, ...] | None = None,
    first_name_input: str | None = None,
    last_name_input: str | None = None,
    gender: str | None = None,
    birth_date: date | None = None,
    email: str | None = None,
    rules_accepted: bool = False,
    rules_accepted_at: datetime | None = None,
    notifications_allowed: bool | None = None,
    notifications_allowed_at: datetime | None = None,
) -> str:
    """Формирует единый текст review-профиля для финала регистрации и кнопки «Профиль»."""

    notifications_status = "Активны ✅" if notifications_allowed else "Отказ ❌"

    return (
        "🧾 *Профиль пользователя*\n\n"
        f"👤 *Имя:* {first_name_input or 'не указано'}\n"
        f"👥 *Фамилия:* {last_name_input or 'не указана'}\n"
        f"📱 *Телефон:* `{phone_e164}`\n"
        f"⚥ *Пол:* {_format_gender(gender)}\n"
        f"🎂 *Дата рождения:* {_format_birth_date(birth_date)}\n"
        f"📧 *Email:* {email or 'не указан'}\n"
        f"🔗 *Привязанных аккаунтов:* {accounts_count}\n"
        f"📲 *Платформы:* {_format_accounts_platforms(accounts_platforms)}\n"
        f"📩 *Уведомления:* {notifications_status}"
    )


def _format_gender(raw_gender: str | None) -> str:
    """Преобразует внутреннее значение пола в человекочитаемый текст."""

    if raw_gender == "male":
        return "мужской"
    if raw_gender == "female":
        return "женский"
    return "не указан"


def _format_birth_date(raw_birth_date: date | None) -> str:
    """Форматирует дату рождения в формат ДД.ММ.ГГГГ."""

    if raw_birth_date is None:
        return "не указана"
    return raw_birth_date.strftime("%d.%m.%Y")


def _format_accounts_platforms(accounts_platforms: tuple[str, ...] | None) -> str:
    """Форматирует список платформ, к которым привязан пользователь."""

    if not accounts_platforms:
        return "не указаны"
    title_mapping = {
        "telegram": "Telegram",
        "vk": "VK",
        "max": "MAX",
    }
    readable_platforms = [title_mapping.get(platform, platform.upper()) for platform in accounts_platforms]
    return ", ".join(readable_platforms)
