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
BUTTON_VIRTUAL_CARD = "🪪 Виртуальная карта"
BUTTON_SUPPORT = "🆘 Отдел заботы"
BUTTON_VACANCIES = "💼 Вакансии"

BUTTON_SUPPORT_FEEDBACK = "✍️ Оставить отзыв"
BUTTON_SUPPORT_QUESTION = "❓ Мне только спросить"
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
BUTTON_PROFILE_EDIT_CANCEL = "🔙 Назад в профиль"
BUTTON_HELP = "Помощь"
BUTTON_ABOUT = "О проекте"
BUTTON_SEND_PHONE = "📱 Поделиться контактом"
BUTTON_ACCEPT_RULES = "✅ Согласен"
BUTTON_DOCS_LINK = "📄 Открыть документы"
BUTTON_BONUSES = "💰 Бонусы"
BUTTON_NOTIFICATIONS_DOCS = "📄 Условия рассылки"
BUTTON_NOTIFICATIONS_YES = "✅ О да, кидай всё, что есть! 🔥"
BUTTON_NOTIFICATIONS_NO = "❌ Нет, останусь без подарков… 🙁"


CONTACT_SCREEN_TEXTS = {
    "telegram": (
        "📱 Чтобы подключиться к программе лояльности, отправьте номер телефона "
        "текстом в формате +79991234567."
    ),
    "vk": (
        "📱 Чтобы подключиться к программе лояльности, отправьте номер телефона "
        "текстом в формате +79991234567."
    ),
    "max": (
        "📱 Чтобы подключиться к программе лояльности, отправьте номер телефона "
        "текстом в формате +79991234567."
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
        "меню": GuestMenuAction.MAIN_MENU,
        "/menu": GuestMenuAction.MAIN_MENU,
        BUTTON_PROFILE.lower(): GuestMenuAction.PROFILE,
        "профиль": GuestMenuAction.PROFILE,
        BUTTON_PROFILE_EDIT.lower(): GuestMenuAction.PROFILE_EDIT,
        BUTTON_PROFILE_EDIT_FIRST_NAME.lower(): GuestMenuAction.PROFILE_EDIT_FIRST_NAME,
        BUTTON_PROFILE_EDIT_LAST_NAME.lower(): GuestMenuAction.PROFILE_EDIT_LAST_NAME,
        BUTTON_PROFILE_EDIT_GENDER.lower(): GuestMenuAction.PROFILE_EDIT_GENDER,
        BUTTON_PROFILE_EDIT_GENDER_MALE.lower(): GuestMenuAction.PROFILE_EDIT_GENDER_MALE,
        BUTTON_PROFILE_EDIT_GENDER_FEMALE.lower(): GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE,
        BUTTON_PROFILE_EDIT_BIRTH_DATE.lower(): GuestMenuAction.PROFILE_EDIT_BIRTH_DATE,
        BUTTON_PROFILE_EDIT_EMAIL.lower(): GuestMenuAction.PROFILE_EDIT_EMAIL,
        BUTTON_PROFILE_EDIT_CANCEL.lower(): GuestMenuAction.PROFILE_EDIT_CANCEL,
        "/profile": GuestMenuAction.PROFILE,
        BUTTON_HELP.lower(): GuestMenuAction.HELP,
        "/help": GuestMenuAction.HELP,
        BUTTON_ABOUT.lower(): GuestMenuAction.ABOUT,
        "/about": GuestMenuAction.ABOUT,
        BUTTON_SEND_PHONE.lower(): GuestMenuAction.SHARE_CONTACT,
        BUTTON_BALANCE.lower(): GuestMenuAction.BALANCE,
        "мой баланс": GuestMenuAction.BALANCE,
        "баланс": GuestMenuAction.BALANCE,
        BUTTON_BONUSES.lower(): GuestMenuAction.BALANCE,
        BUTTON_VIRTUAL_CARD.lower(): GuestMenuAction.VIRTUAL_CARD,
        "виртуальная карта": GuestMenuAction.VIRTUAL_CARD,
        BUTTON_SUPPORT.lower(): GuestMenuAction.SUPPORT,
        "отдел заботы": GuestMenuAction.SUPPORT,
        "поддержка": GuestMenuAction.SUPPORT,
        BUTTON_VACANCIES.lower(): GuestMenuAction.VACANCIES,
        "вакансии": GuestMenuAction.VACANCIES,
        BUTTON_SUPPORT_FEEDBACK.lower(): GuestMenuAction.SUPPORT_FEEDBACK,
        "оставить отзыв": GuestMenuAction.SUPPORT_FEEDBACK,
        BUTTON_SUPPORT_QUESTION.lower(): GuestMenuAction.SUPPORT_QUESTION,
        "задать вопрос": GuestMenuAction.SUPPORT_QUESTION,
        "мне только спросить": GuestMenuAction.SUPPORT_QUESTION,
        BUTTON_MY_TICKETS.lower(): GuestMenuAction.MY_TICKETS,
        "мои обращения": GuestMenuAction.MY_TICKETS,
        BUTTON_SUPPORT_CONTACTS.lower(): GuestMenuAction.SUPPORT_CONTACTS,
        "контакты": GuestMenuAction.SUPPORT_CONTACTS,
        BUTTON_BACK_TO_MAIN.lower(): GuestMenuAction.BACK_TO_MAIN,
        BUTTON_BACK_TO_SUPPORT.lower(): GuestMenuAction.BACK_TO_SUPPORT,
        BUTTON_DOCS_LINK.lower(): GuestMenuAction.OPEN_DOCS,
        BUTTON_ACCEPT_RULES.lower(): GuestMenuAction.ACCEPT_RULES,
        BUTTON_NOTIFICATIONS_YES.lower(): GuestMenuAction.NOTIFY_YES,
        BUTTON_NOTIFICATIONS_NO.lower(): GuestMenuAction.NOTIFY_NO,
    }
    return mapping.get(normalized)


def build_start_rules_screen() -> MenuScreenContract:
    """Экран приветствия гостя с запросом согласия (эталонный текст)."""

    return MenuScreenContract(
        screen_id="start_rules",
        text=(
            "👋 Здравствуй Друг!\n\n"
            "Добро пожаловать к нам в гости!\n\n"
            "📜 Для начала нам необходимо получить твоё согласие на обработку персональных данных "
            "и согласие с политикой конфиденциальности.\n\n"
            "👉 Ознакомься с документами по ссылке ниже и отправь сообщение «✅ Согласен».\n\n"
            "После ознакомления отправьте сообщение «✅ Согласен»."
        ),
        buttons=(
            MenuButtonContract(
                action=GuestMenuAction.OPEN_DOCS,
                label=BUTTON_DOCS_LINK,
                url="https://sagur.24vds.ru/agreement/#",
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


def build_notifications_consent_screen(profile_text: str | None = None) -> MenuScreenContract:
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
                url="https://sagur.24vds.ru/notifications/#",
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


def build_legacy_upgrade_screen() -> MenuScreenContract:
    """Экран запуска обновления для legacy-пользователя.

    Сценарий intentionally пересекается с обычной регистрации:
    на первом этапе мы также запрашиваем подтверждение номера телефона.
    """

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
            MenuButtonContract(action=GuestMenuAction.SUPPORT, label=BUTTON_SUPPORT),
            MenuButtonContract(action=GuestMenuAction.VACANCIES, label=BUTTON_VACANCIES),
            MenuButtonContract(action=GuestMenuAction.PROFILE, label=BUTTON_PROFILE),
        ),
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
            "Ближайшая дата сгорания: —\n"
            "Количество бонусов к сгоранию: —\n"
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
    """Экран раздела «Оставить отзыв»."""

    return MenuScreenContract(
        screen_id="support_feedback",
        text=(
            "✍️ *Оставить отзыв*\n\n"
            "Мы будем рады узнать ваше мнение! Перейдите по ссылке ниже:\n"
            "👉 https://example.com/feedback"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_SUPPORT, label=BUTTON_BACK_TO_SUPPORT),),
        parse_mode="markdown",
    )


def build_support_question_screen() -> MenuScreenContract:
    """Экран начала сценария обращения в поддержку."""

    return MenuScreenContract(
        screen_id="support_question",
        text=(
            "❓ *Мне только спросить*\n\n"
            "Пожалуйста, отправьте ваш вопрос, и наш модератор свяжется с вами в ближайшее время.\n\n"
            "Введите ваш вопрос:"
        ),
        buttons=(MenuButtonContract(action=GuestMenuAction.BACK_TO_SUPPORT, label=BUTTON_BACK_TO_SUPPORT),),
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
            "🆘 Помощь по боту\n\n"
            "• /start — запуск и регистрация\n"
            "• /menu — открыть главное меню\n"
            "• Мой профиль — показать ваш телефон и привязки\n"
            "• Отдел заботы — связь с поддержкой"
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

    return MenuScreenContract(
        screen_id="profile",
        text=build_profile_review_text(
            phone_e164=phone_e164,
            accounts_count=accounts_count,
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
        buttons=(
            MenuButtonContract(action=GuestMenuAction.PROFILE_EDIT, label=BUTTON_PROFILE_EDIT),
            MenuButtonContract(action=GuestMenuAction.BACK_TO_MAIN, label=BUTTON_BACK_TO_MAIN),
        ),
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


def build_profile_review_text(
    *,
    phone_e164: str,
    accounts_count: int,
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

    return (
        "🧾 *Профиль пользователя*\n\n"
        f"👤 *Имя:* {first_name_input or 'не указано'}\n"
        f"👥 *Фамилия:* {last_name_input or 'не указана'}\n"
        f"📱 *Телефон:* `{phone_e164}`\n"
        f"⚥ *Пол:* {_format_gender(gender)}\n"
        f"🎂 *Дата рождения:* {_format_birth_date(birth_date)}\n"
        f"📧 *Email:* {email or 'не указан'}\n"
        f"📜 *Согласие с правилами:* {_format_rules_choice(rules_accepted)}\n"
        f"🕒 *Дата согласия с правилами:* {_format_datetime(rules_accepted_at)}\n"
        f"📢 *Согласие на рассылку:* {_format_notifications_choice(notifications_allowed)}\n"
        f"🕒 *Дата решения по рассылке:* {_format_datetime(notifications_allowed_at)}\n"
        f"🔗 *Привязанных аккаунтов:* {accounts_count}"
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


def _format_datetime(raw_datetime: datetime | None) -> str:
    """Форматирует дату/время юридически значимых согласий."""

    if raw_datetime is None:
        return "не зафиксирована"
    return raw_datetime.strftime("%d.%m.%Y %H:%M:%S")


def _format_rules_choice(accepted: bool) -> str:
    """Форматирует выбор пользователя по согласию с правилами."""

    return "✅ принято" if accepted else "❌ не принято"


def _format_notifications_choice(allowed: bool | None) -> str:
    """Форматирует выбор пользователя по уведомлениям."""

    if allowed is True:
        return "✅ согласен"
    if allowed is False:
        return "❌ отказался"
    return "не выбран"

