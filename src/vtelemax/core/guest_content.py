"""Единый контент гостевых сценариев (эталон: Telegram-прототип).

В модуле хранятся:

1. тексты экранов;
2. подписи кнопок;
3. правила преобразования текстовой команды в доменное действие меню.
"""

from __future__ import annotations

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
BUTTON_PROFILE = "Мой профиль"
BUTTON_HELP = "Помощь"
BUTTON_ABOUT = "О проекте"
BUTTON_SEND_PHONE = "Отправить номер телефона"
BUTTON_ACCEPT_RULES = "✅ Согласен"


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
        "/profile": GuestMenuAction.PROFILE,
        BUTTON_HELP.lower(): GuestMenuAction.HELP,
        "/help": GuestMenuAction.HELP,
        BUTTON_ABOUT.lower(): GuestMenuAction.ABOUT,
        "/about": GuestMenuAction.ABOUT,
        BUTTON_SEND_PHONE.lower(): GuestMenuAction.SHARE_CONTACT,
        BUTTON_BALANCE.lower(): GuestMenuAction.BALANCE,
        BUTTON_VIRTUAL_CARD.lower(): GuestMenuAction.VIRTUAL_CARD,
        BUTTON_SUPPORT.lower(): GuestMenuAction.SUPPORT,
        BUTTON_VACANCIES.lower(): GuestMenuAction.VACANCIES,
        BUTTON_SUPPORT_FEEDBACK.lower(): GuestMenuAction.SUPPORT_FEEDBACK,
        BUTTON_SUPPORT_QUESTION.lower(): GuestMenuAction.SUPPORT_QUESTION,
        BUTTON_MY_TICKETS.lower(): GuestMenuAction.MY_TICKETS,
        BUTTON_SUPPORT_CONTACTS.lower(): GuestMenuAction.SUPPORT_CONTACTS,
        BUTTON_BACK_TO_MAIN.lower(): GuestMenuAction.BACK_TO_MAIN,
        BUTTON_BACK_TO_SUPPORT.lower(): GuestMenuAction.BACK_TO_SUPPORT,
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
            "👉 Ознакомься с документами по ссылке ниже и отправь сообщение «✅ Согласен»."
        ),
        buttons=(
            MenuButtonContract(action=GuestMenuAction.SHARE_CONTACT, label=BUTTON_ACCEPT_RULES),
        ),
    )


def build_start_contact_screen() -> MenuScreenContract:
    """Экран запроса номера телефона (эталонный текст)."""

    return MenuScreenContract(
        screen_id="start_contact",
        text=(
            "📱 Чтобы подключиться к программе лояльности, нажми кнопку «Поделиться контактом».\n"
            "После этого мы будем знакомы чуть ближе."
        ),
        buttons=(
            MenuButtonContract(action=GuestMenuAction.SHARE_CONTACT, label=BUTTON_SEND_PHONE),
        ),
    )


def build_legacy_upgrade_screen() -> MenuScreenContract:
    """Экран запуска обновления для legacy-пользователя.

    Сценарий intentionally пересекается с обычной регистрацией:
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
            MenuButtonContract(action=GuestMenuAction.HELP, label=BUTTON_HELP),
            MenuButtonContract(action=GuestMenuAction.ABOUT, label=BUTTON_ABOUT),
            MenuButtonContract(action=GuestMenuAction.MAIN_MENU, label=BUTTON_MAIN_MENU),
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


def build_profile_screen(phone_e164: str, accounts_count: int) -> MenuScreenContract:
    """Экран профиля зарегистрированного пользователя."""

    return MenuScreenContract(
        screen_id="profile",
        text=(
            "Ваш профиль:\n"
            f"Телефон: {phone_e164}\n"
            f"Привязанных аккаунтов: {accounts_count}"
        ),
    )
