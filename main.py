import argparse
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
import xml.etree.ElementTree as ET

import pandas as pd
import requests

logger = logging.getLogger("fis_gia_export")

# Столбцы, обязательные в reestr.xlsx для успешной генерации XML
REQUIRED_COLUMNS = [
    'Номер', 'Источник',
    'Фамилия', 'Имя', 'Отчество', 'Пол', 'СНИЛС', 'Электронная почта',
    'Место регистрации', 'Полный адрес', 'Квартира',
    'Изменение статуса',
    'Тип ГИА',
    'Специальность', 'Форма обучения', 'Финансирование',
    'Серия ДУЛ', 'Номер ДУЛ', 'Код подразделения ДУЛ', 'Дата выдачи ДУЛ', 'Кем выдан ДУЛ',
    'Дата рождения', 'Гражданство',
    'Серия документа об образовании', 'Номер документа об образовании',
    'Дата выдачи документа об образовании',
    'Организация, выдавшая документ об образовании (школа)', 'Год окончания', 'Средний балл',
]

# Значения по умолчанию для параметров, которые ранее были захардкожены в коде.
# Их можно переопределить в config.txt.
DEFAULT_CONFIG = {
    'SchoolCertRegionID': '77',
    'NationalityTypeID': '1',
    'ReleaseCountryID': '1',
    'MoscowRegionID': '77',
    'DefaultRegionID': '1000',
}


def setup_logging(verbose=False):
    """Настройка логирования вместо print"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def read_config():
    """Чтение конфигурационных данных"""
    config = dict(DEFAULT_CONFIG)  # значения по умолчанию, могут быть переопределены файлом
    with open('config.txt', 'r', encoding='utf-8') as f:
        for line in f:
            if ':' in line:
                key, value = line.strip().split(':', 1)
                config[key.strip()] = value.strip()
    return config


def validate_columns(df):
    """Проверка, что все обязательные столбцы присутствуют в DataFrame"""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            "В файле xlsx/reestr.xlsx отсутствуют обязательные столбцы: "
            + ", ".join(missing)
        )
    logger.debug("Проверка столбцов пройдена, все обязательные столбцы присутствуют")


def calculate_competitive_groups(df):
    """Подсчет конкурсных групп для каждой специальности"""
    # Группировка по специальности, форме обучения и финансированию
    grouped = df.groupby(['Специальность', 'Форма обучения', 'Финансирование']).size().reset_index(name='count')

    competitive_groups = []
    uid_pk = read_config().get('UID_PK', '')

    for idx, row in grouped.iterrows():
        group_id = f"{uid_pk}_{idx+1}"
        speciality = row['Специальность']
        form = row['Форма обучения']
        financing = row['Финансирование']

        competitive_groups.append({
            'id': group_id,
            'speciality': speciality,
            'form': form,
            'financing': financing,
            'count': row['count']
        })

    return competitive_groups


def check_existing_groups():
    """Проверка наличия конкурсных групп в config.txt"""
    try:
        with open('config.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Найдем строку с Konkursy
        konkursy_index = -1
        for i, line in enumerate(lines):
            if 'Konkursy:' in line:
                konkursy_index = i
                break

        if konkursy_index != -1:
            # Проверяем, есть ли строки после Konkursy:
            for i in range(konkursy_index + 1, len(lines)):
                line = lines[i].strip()
                if line:  # Если есть непустая строка после Konkursy:
                    return True

        return False
    except FileNotFoundError:
        return False


def get_existing_groups():
    """Получение существующих конкурсных групп из config.txt"""
    groups = []
    try:
        with open('config.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Найдем строку с Konkursy
        konkursy_index = -1
        for i, line in enumerate(lines):
            if 'Konkursy:' in line:
                konkursy_index = i
                break

        if konkursy_index != -1:
            # Читаем строки после Konkursy:
            for i in range(konkursy_index + 1, len(lines)):
                line = lines[i].strip()
                if line:  # Если есть непустая строка
                    parts = line.split(' ', 1)  # Разделяем ID и описание
                    if len(parts) >= 2:
                        group_id = parts[0]
                        description = parts[1]
                        # Парсим описание (Специальность Форма Финансирование)
                        desc_parts = description.rsplit(' ', 2)  # Разделяем с конца
                        if len(desc_parts) >= 3:
                            speciality = desc_parts[0]
                            form = desc_parts[1]
                            financing = desc_parts[2]
                            groups.append({
                                'id': group_id,
                                'speciality': speciality,
                                'form': form,
                                'financing': financing
                            })

        return groups
    except FileNotFoundError:
        return []


def update_config_with_groups(competitive_groups):
    """Обновление config.txt с конкурсными группами"""
    # Читаем существующий файл
    with open('config.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Найдем строку с Konkursy и добавим после неё группы
    konkursy_index = -1
    for i, line in enumerate(lines):
        if 'Konkursy:' in line:
            konkursy_index = i
            break

    if konkursy_index != -1:
        # Удаляем все строки после Konkursy:
        new_lines = lines[:konkursy_index + 1]

        # Добавляем новые конкурсные группы
        for group in competitive_groups:
            group_line = f"{group['id']} {group['speciality']} {group['form']} {group['financing']}\n"
            new_lines.append(group_line)

        # Записываем обновленный файл
        with open('config.txt', 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info("Добавлено %d конкурсных групп в config.txt", len(competitive_groups))
    else:
        logger.error("Не найдена строка 'Konkursy:' в config.txt")


def get_competitive_group_id(row, competitive_groups):
    """Получение ID конкурсной группы для строки данных"""
    for group in competitive_groups:
        if (group['speciality'] == row['Специальность'] and
                group['form'] == row['Форма обучения'] and
                group['financing'] == row['Финансирование']):
            return group['id']
    return None


def format_snils(snils):
    """Форматирование СНИЛС в формат XXX-XXX-XXX XX"""
    if pd.isna(snils):
        return ""

    # Удаляем все нецифровые символы
    snils_digits = re.sub(r'\D', '', str(snils))

    # if len(snils_digits) == 11:
    #     return f"{snils_digits[:3]}-{snils_digits[3:6]}-{snils_digits[6:9]} {snils_digits[9:]}"
    return str(snils_digits)


def format_gender(gender):
    """Преобразование пола в ID (Женский = 2, Мужской = 1)"""
    if pd.isna(gender):
        return "1"
    gender_str = str(gender).lower()
    if 'женский' in gender_str or 'ж' in gender_str:
        return "2"
    return "1"


def format_region(region, config):
    """Преобразование региона в ID (Москва = MoscowRegionID, иначе = DefaultRegionID)"""
    if pd.isna(region):
        return config.get('DefaultRegionID', DEFAULT_CONFIG['DefaultRegionID'])
    region_str = str(region).lower()
    if 'москва' in region_str:
        return config.get('MoscowRegionID', DEFAULT_CONFIG['MoscowRegionID'])
    return config.get('DefaultRegionID', DEFAULT_CONFIG['DefaultRegionID'])


def format_date(date_val):
    """Форматирование даты в формат YYYY-MM-DD"""
    if pd.isna(date_val):
        return ""

    if isinstance(date_val, str):
        # Пытаемся парсить строку с учетом русского формата дат
        try:
            date_obj = pd.to_datetime(date_val, dayfirst=True)
            return date_obj.strftime('%Y-%m-%d')
        except Exception:
            return str(date_val)
    elif hasattr(date_val, 'strftime'):
        return date_val.strftime('%Y-%m-%d')
    else:
        return str(date_val)


def format_datetime(date_val):
    """Форматирование даты в формат YYYY-MM-DDTHH:MM:SS"""
    if pd.isna(date_val):
        return ""

    if isinstance(date_val, str):
        try:
            date_obj = pd.to_datetime(date_val, dayfirst=True)
            return date_obj.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            return str(date_val)
    elif hasattr(date_val, 'strftime'):
        return date_val.strftime('%Y-%m-%dT%H:%M:%S')
    else:
        return str(date_val)


def format_passport_series(value):
    if len(value) < 4:
        result = ''
        for i in range(0, 4 - len(value)):
            result += '0'
        result += value
        return result
    return value


def format_passport_number(value):
    if len(value) < 6:
        result = ''
        for i in range(0, 6 - len(value)):
            result += '0'
        result += value
        return result
    return value


def format_attestat_number(value):
    if len(value) < 14:
        result = ''
        for i in range(0, 14 - len(value)):
            result += '0'
        result += value
        return result
    return value


def safe_str(value):
    """Безопасное преобразование в строку"""
    if pd.isna(value):
        return ""
    return str(value)


def generate_xml(df, competitive_groups):
    """Генерация XML из DataFrame"""
    config = read_config()

    # Создаем корневой элемент
    root = ET.Element('Root')
    root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

    # AuthData
    auth_data = ET.SubElement(root, 'AuthData')
    auth_data.set('xmlns:xs', 'http://www.w3.org/2001/XMLSchema')

    login = ET.SubElement(auth_data, 'Login')
    login.text = config.get('Login', '')

    password = ET.SubElement(auth_data, 'Pass')
    password.text = config.get('Password', '')

    # PackageData
    package_data = ET.SubElement(root, 'PackageData')
    package_data.set('xmlns:xs', 'http://www.w3.org/2001/XMLSchema')

    applications = ET.SubElement(package_data, 'Applications')

    # Обрабатываем каждую строку из Excel
    for index, row in df.iterrows():
        application = ET.SubElement(applications, 'Application')

        # UID
        uid = ET.SubElement(application, 'UID')
        application_number = f"{safe_str(row['Номер'])}"
        uid.text = application_number

        # FromEPGU
        from_epgu = ET.SubElement(application, 'FromEPGU')
        from_epgu.text = "1" if safe_str(row['Источник']) == 'МПГУ' else "0"

        # ApplicationNumber
        app_number = ET.SubElement(application, 'ApplicationNumber')
        app_number.text = application_number

        # Entrant
        entrant = ET.SubElement(application, 'Entrant')

        entrant_uid = ET.SubElement(entrant, 'UID')
        entrant_uid.text = application_number + "_entrant"

        last_name = ET.SubElement(entrant, 'LastName')
        last_name.text = safe_str(row['Фамилия'])

        first_name = ET.SubElement(entrant, 'FirstName')
        first_name.text = safe_str(row['Имя'])

        middle_name = ET.SubElement(entrant, 'MiddleName')
        middle_name.text = safe_str(row['Отчество'])

        gender_id = ET.SubElement(entrant, 'GenderID')
        gender_id.text = format_gender(row['Пол'])

        snils = ET.SubElement(entrant, 'SNILS')
        snils.text = format_snils(row['СНИЛС'])

        # EmailOrMailAddress
        email_or_mail = ET.SubElement(entrant, 'EmailOrMailAddress')

        email = ET.SubElement(email_or_mail, 'Email')
        email.text = safe_str(row['Электронная почта'])

        mail_address = ET.SubElement(email_or_mail, 'MailAddress')

        region_id = ET.SubElement(mail_address, 'RegionID')
        region_id.text = format_region(row['Место регистрации'], config)

        town_type_id = ET.SubElement(mail_address, 'TownTypeID')
        town_type_id.text = '4'

        address = ET.SubElement(mail_address, 'Address')
        address.text = safe_str(f"{row['Полный адрес']}, {row['Квартира']}")

        # RegistrationDate
        reg_date = ET.SubElement(application, 'RegistrationDate')
        reg_date.text = format_datetime(row['Изменение статуса'])

        # NeedHostel
        need_hostel = ET.SubElement(application, 'NeedHostel')
        need_hostel.text = 'false'

        # StatusID
        status_id = ET.SubElement(application, 'StatusID')
        status_id.text = '4'

        # After11
        after11 = ET.SubElement(application, 'After11')
        after11.text = '1' if (row['Тип ГИА'] == '') else '0'

        # FinSourceAndEduForms
        fin_source_edu_forms = ET.SubElement(application, 'FinSourceAndEduForms')

        fin_source_edu_form = ET.SubElement(fin_source_edu_forms, 'FinSourceEduForm')

        competitive_group_uid = ET.SubElement(fin_source_edu_form, 'CompetitiveGroupUID')
        group_id = get_competitive_group_id(row, competitive_groups)
        if group_id is None:
            logger.warning(
                "Не найдена конкурсная группа для заявления %s (%s / %s / %s)",
                application_number, row['Специальность'], row['Форма обучения'], row['Финансирование']
            )
        competitive_group_uid.text = group_id

        # ApplicationDocuments
        app_documents = ET.SubElement(application, 'ApplicationDocuments')

        # IdentityDocument
        identity_doc = ET.SubElement(app_documents, 'IdentityDocument')

        identity_uid = ET.SubElement(identity_doc, 'UID')
        identity_uid.text = application_number + "_identity"

        id_last_name = ET.SubElement(identity_doc, 'LastName')
        id_last_name.text = safe_str(row['Фамилия'])

        id_first_name = ET.SubElement(identity_doc, 'FirstName')
        id_first_name.text = safe_str(row['Имя'])

        id_middle_name = ET.SubElement(identity_doc, 'MiddleName')
        id_middle_name.text = safe_str(row['Отчество'])

        id_gender_id = ET.SubElement(identity_doc, 'GenderID')
        id_gender_id.text = format_gender(row['Пол'])

        doc_series = ET.SubElement(identity_doc, 'DocumentSeries')
        doc_series.text = format_passport_series(safe_str(row['Серия ДУЛ']))

        doc_number = ET.SubElement(identity_doc, 'DocumentNumber')
        doc_number.text = format_passport_number(safe_str((row['Номер ДУЛ'])))

        subdivision_code = ET.SubElement(identity_doc, 'SubdivisionCode')
        subdivision_code.text = safe_str(row['Код подразделения ДУЛ'])

        doc_date = ET.SubElement(identity_doc, 'DocumentDate')
        doc_date.text = format_date(row['Дата выдачи ДУЛ'])

        doc_organization = ET.SubElement(identity_doc, 'DocumentOrganization')
        doc_organization.text = safe_str(row['Кем выдан ДУЛ'])

        id_doc_type_id = ET.SubElement(identity_doc, 'IdentityDocumentTypeID')
        id_doc_type_id.text = '1'

        nationality_type_id = ET.SubElement(identity_doc, 'NationalityTypeID')
        nationality_type_id.text = config.get('NationalityTypeID', DEFAULT_CONFIG['NationalityTypeID'])

        birth_date = ET.SubElement(identity_doc, 'BirthDate')
        birth_date.text = format_date(row['Дата рождения'])

        birth_place = ET.SubElement(identity_doc, 'BirthPlace')
        birth_place.text = safe_str(row['Гражданство'])

        release_country_id = ET.SubElement(identity_doc, 'ReleaseCountryID')
        release_country_id.text = config.get('ReleaseCountryID', DEFAULT_CONFIG['ReleaseCountryID'])

        release_place = ET.SubElement(identity_doc, 'ReleasePlace')
        release_place.text = safe_str(row['Гражданство'])

        original_receive_date = ET.SubElement(identity_doc, 'OriginalReceivedDate')
        original_receive_date.text = format_date(row['Изменение статуса'])

        # EduDocuments
        edu_documents = ET.SubElement(app_documents, 'EduDocuments')

        edu_document = ET.SubElement(edu_documents, 'EduDocument')

        school_cert = ET.SubElement(edu_document, 'SchoolCertificateBasicDocument')

        school_uid = ET.SubElement(school_cert, 'UID')
        school_uid.text = application_number + "_attestat"

        # Серия документа об образовании (если не пусто)
        if not pd.isna(row['Серия документа об образовании']) and str(row['Серия документа об образовании']).strip():
            school_doc_series = ET.SubElement(school_cert, 'DocumentSeries')
            school_doc_series.text = safe_str(row['Серия документа об образовании'])

        school_doc_number = ET.SubElement(school_cert, 'DocumentNumber')
        school_doc_number.text = format_attestat_number(safe_str(row['Номер документа об образовании']))

        school_doc_date = ET.SubElement(school_cert, 'DocumentDate')
        school_doc_date.text = format_date(row['Дата выдачи документа об образовании'])

        school_region_id = ET.SubElement(school_cert, 'RegionId')
        school_region_id.text = config.get('SchoolCertRegionID', DEFAULT_CONFIG['SchoolCertRegionID'])

        school_doc_org = ET.SubElement(school_cert, 'DocumentOrganization')
        school_doc_org.text = safe_str(row['Организация, выдавшая документ об образовании (школа)'])

        end_year = ET.SubElement(school_cert, 'EndYear')
        end_year.text = safe_str(row['Год окончания'])

        gpa = ET.SubElement(school_cert, 'GPA')
        gpa.text = safe_str(row['Средний балл'])

        original_receive_date = ET.SubElement(school_cert, 'OriginalReceivedDate')
        original_receive_date.text = format_date(row['Изменение статуса'])

    return root


def pretty_format_xml(xml_input):
    """Форматирование XML с переносами строк после каждого закрытого тега."""
    pretty_xml = re.sub(r'(>)(<)', r'\1\n\2', xml_input)
    return pretty_xml


def send_to_fis_gia(xml_filename):
    """Отправка XML файла в ФИС ГИА"""
    config = read_config()
    server_url = config.get('Server', '')

    if not server_url:
        logger.error("Не найден адрес сервера в config.txt")
        return False

    if not os.path.exists(xml_filename):
        logger.error("Файл %s не найден", xml_filename)
        return False

    try:
        # Используем URL из конфига как есть (он уже содержит полный путь)
        full_url = server_url

        logger.info("Отправка пакета на сервер: %s", full_url)
        logger.info("Файл: %s", xml_filename)

        # Читаем XML файл
        with open(xml_filename, 'r', encoding='utf-8') as f:
            xml_content = f.read()

        # Подготавливаем заголовки
        headers = {
            'Content-Type': 'text/xml'
        }

        # Отправляем POST запрос
        response = requests.post(
            full_url,
            data=xml_content.encode('utf-8'),
            headers=headers,
            timeout=30
        )

        logger.info("Код ответа: %s", response.status_code)
        logger.debug("Заголовки ответа: %s", response.headers)

        if response.status_code == 200:
            logger.info("Пакет успешно отправлен в ФИС ГИА!")
            if response.text:
                logger.info("Ответ сервера: %s", response.text)
            return True
        elif response.status_code == 404:
            logger.error("Ошибка 404: Не найден указанный путь на сервере")
            logger.error("Проверьте URL в config.txt: %s", full_url)
            if response.text:
                logger.error("Ошибка сервера: %s", response.text)
            return False
        else:
            logger.error("Ошибка отправки: %s", response.status_code)
            if response.text:
                logger.error("Ошибка сервера: %s", response.text)
            return False

    except requests.exceptions.Timeout:
        logger.error("Превышено время ожидания ответа от сервера")
        return False
    except requests.exceptions.ConnectionError:
        logger.error("Не удалось соединиться с сервером")
        return False
    except Exception as e:
        logger.error("Ошибка отправки: %s", str(e))
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Генерация и отправка XML-пакета заявлений абитуриентов в ФИС ГИА"
    )
    send_group = parser.add_mutually_exclusive_group()
    send_group.add_argument(
        '--send', action='store_true',
        help="Отправить сформированный пакет в ФИС ГИА без интерактивного запроса"
    )
    send_group.add_argument(
        '--no-send', action='store_true',
        help="Не отправлять пакет и не задавать вопрос (только сгенерировать XML)"
    )
    parser.add_argument(
        '--input', default='xlsx/reestr.xlsx',
        help="Путь к файлу реестра Excel (по умолчанию xlsx/reestr.xlsx)"
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help="Подробное логирование (DEBUG)"
    )
    return parser.parse_args()


def main():
    """Основная функция"""
    args = parse_args()
    setup_logging(args.verbose)

    logger.info("Загрузка данных из Excel: %s", args.input)
    df = pd.read_excel(args.input)

    try:
        validate_columns(df)
    except ValueError as e:
        logger.error(str(e))
        return

    # Фильтруем только записи с гражданством "Российская Федерация"
    original_count = len(df)
    df = df[df['Гражданство'] == 'Российская Федерация']
    logger.info("Исходное количество записей: %d", original_count)
    logger.info("Записей с гражданством 'Российская Федерация': %d", len(df))

    # Проверяем, есть ли уже конкурсные группы в config.txt
    if check_existing_groups():
        logger.info("Конкурсные группы уже существуют в config.txt")
        competitive_groups = get_existing_groups()
        logger.info("Используем %d существующих конкурсных групп:", len(competitive_groups))
        for group in competitive_groups:
            logger.info("  %s - %s %s %s", group['id'], group['speciality'], group['form'], group['financing'])
    else:
        logger.info("Подсчет конкурсных групп...")
        competitive_groups = calculate_competitive_groups(df)

        logger.info("Найдено %d конкурсных групп:", len(competitive_groups))
        for group in competitive_groups:
            logger.info(
                "  %s - %s %s %s (%d заявлений)",
                group['id'], group['speciality'], group['form'], group['financing'], group['count']
            )

        logger.info("Обновление config.txt...")
        update_config_with_groups(competitive_groups)

    logger.info("Генерация XML...")
    xml_root = generate_xml(df, competitive_groups)

    # Форматируем и сохраняем XML
    xml_str = ET.tostring(xml_root, encoding='unicode')

    # Добавляем XML декларацию
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
    xml_output = pretty_format_xml(xml_output)

    # Получаем текущую дату и время
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_filename = f'output_{now}.xml'

    # Сохраняем в файл
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(xml_output)

    logger.info("XML файл успешно создан: %s", output_filename)
    logger.info("Обработано %d записей", len(df))

    # Неинтерактивные режимы отправки, заданные через CLI
    if args.send:
        logger.info("Инициируется отправка пакета (--send)...")
        success = send_to_fis_gia(output_filename)
        if success:
            logger.info("Пакет успешно отправлен!")
        else:
            logger.error("Ошибка при отправке пакета.")
        return

    if args.no_send:
        logger.info("Отправка пакета отключена (--no-send).")
        return

    # Интерактивный запрос об отправке пакета
    while True:
        answer = input("\nОтправить пакет в ФИС ГИА? Да(д)/Нет(н): ").strip().lower()
        if answer in ['д', 'да', 'y', 'yes']:
            logger.info("Инициируется отправка пакета...")
            success = send_to_fis_gia(output_filename)
            if success:
                logger.info("Пакет успешно отправлен!")
            else:
                logger.error("Ошибка при отправке пакета.")
            break
        elif answer in ['н', 'нет', 'n', 'no']:
            logger.info("Отправка пакета отменена.")
            break
        else:
            print("Пожалуйста, введите 'д' для отправки или 'н' для отмены.")


if __name__ == "__main__":
    main()
