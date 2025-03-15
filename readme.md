# Женственность - Бот для обучения

## Описание

Этот бот создан для предоставления доступа к курсу "Женственность", состоящему из 11 уроков. Каждый урок выдается последовательно через каждые три дня после оплаты. Бот поддерживает три тарифа: без проверки домашних заданий, с проверкой домашних заданий и личное сопровождение.

courses/
  femininity/
    lesson1.txt
    lesson1_image1.jpg
    lesson1_audio_5m.mp3 - отправка через 5 мин
    lesson1_audio_5min.mp3 - так тож работает
    lesson1_video_2h.mp4
    lesson1_video_2hour.mp4
    lesson2_p4.mp4 - предварительные файлы для второго урока. отправляются по кнопке (тыкает юзер сам) после сдачи домашки по первому уроку


## Установка и запуск

### Локальная разработка

1. **Установите Python**: Убедитесь, что у вас установлен Python 3.7 или выше.
2. **Склонируйте репозиторий**:
    ```bash 
    git clone https://github.com/andrjur/AntonyBot
    cd AntonyBot
    ```
3. **Создайте виртуальное окружение** (рекомендуется):
    ```bash
    python -m venv venv
    source venv/bin/activate  # На Windows используйте `venv\Scripts\activate`
    ```
4. **Установите зависимости**:
    ```bash
    pip install -r requirements.txt
    ```
5. **Настройте базу данных**:
    - Создайте файл `users.db` в корневой директории проекта.
    - Запустите скрипт для создания таблицы пользователей (если это не сделано автоматически).
6. **Запустите бота**:
    ```bash
    python main222.py
    ```

### Развертывание на Railway

1. **Создайте аккаунт на Railway** и создайте новый проект.
2. **Подключите репозиторий GitHub** к вашему проекту на Railway.
3. **Настройте переменные окружения**:
    - `TELEGRAM_BOT_TOKEN`: Токен вашего Telegram-бота.
4. **Разверните приложение**:
    - Railway автоматически обнаружит `main.py` и запустит его.

## Использование

### **Команды бота**

1. **`/start`**:
   - Начать взаимодействие с ботом.
   - Отображает приветственное сообщение и основное меню.

2. **`/tariff`**:
   - Выбрать или изменить тариф.
   - Позволяет пользователю выбрать один из доступных тарифов (например, "Без проверки д/з", "С проверкой д/з", "Личное сопровождение").

3. **`/lessons`**:
   - Получить доступ к текущему уроку.
   - Отправляет текст урока и связанные файлы (изображения, видео, аудио) с учетом задержек.

4. **`/support`**:
   - Записаться на личную консультацию (доступно только для тарифа "Личное сопровождение").
   - Позволяет отправить запрос в поддержку.

---

### **Кнопки управления**

#### 1. **Основное меню**
- **"🖼 Галерея ДЗ"**:
  - Просмотр выполненных домашних заданий других участников.
  - Кнопка доступна для всех пользователей.

- **"⚙ Настройка Курса ⏰(время)"**:
  - Настройка времени напоминаний (утренние и вечерние).
  - Позволяет пользователю изменить время получения уведомлений.

- **"💰 Тарифы и Бонусы <- тут много"**:
  - Отображает список доступных тарифов и бонусов.
  - Пользователь может выбрать тариф или активировать акцию.

- **"🙋 ПоДдержка"**:
  - Отправка запроса в поддержку.
  - Позволяет пользователю описать проблему или задать вопрос.

---

#### 2. **Управление курсом**
- **"Сменить $$$ тариф"**:
  - Изменение текущего тарифа.
  - Пользователь может перейти на другой тариф (например, с "Без проверки д/з" на "С проверкой д/з").

- **"Мои курсы"**:
  - Отображение списка активных курсов пользователя.
  - Позволяет переключаться между курсами.

- **"История ДЗ"**:
  - Просмотр истории отправленных домашних заданий.
  - Показывает статус каждого задания (например, "На проверке", "Одобрено").

---

#### 3. **Тарифы**
- **"Купить"**:
  - Кнопка для покупки выбранного тарифа.
  - Открывает инструкцию по оплате.

- **"В подарок"**:
  - Кнопка для отправки тарифа другому пользователю.
  - Запрашивает ID получателя.

- **"Я оплатил"**:
  - Подтверждение оплаты тарифа.
  - После нажатия кнопки администратору отправляется уведомление о необходимости проверки оплаты.

- **"Назад к тарифам"**:
  - Возврат к списку доступных тарифов.

---

#### 4. **Домашние задания**
- **"✅ Принять домашнее задание"**:
  - Кнопка для самопроверки домашнего задания (доступна для тарифа "Без проверки д/з").
  - Пользователь может самостоятельно подтвердить выполнение задания.

- **"Отправить домашнее задание"**:
  - Кнопка для отправки домашнего задания администратору (доступна для тарифа "С проверкой д/з").
  - После отправки задания администратору отображается статус "На проверке".

---

#### 5. **Предварительные материалы**
- **"🙇🏼 Предварительные материалы к след. уроку"**:
  - Кнопка для получения предварительных материалов для следующего урока.
  - Доступна после сдачи домашнего задания за текущий урок.

---

#### 6. **Акции и скидки**
- **"В подарок"**:
  - Кнопка для отправки акции другому пользователю.
  - Запрашивает ID получателя.

- **"Подтвердить скидку"**:
  - Кнопка для администратора, чтобы подтвердить скидку для пользователя.
  - После подтверждения пользователю предоставляется доступ к курсу.

---

#### 7. **Настройка напоминаний**
- **"Установить время напоминаний"**:
  - Кнопка для изменения времени утренних и вечерних напоминаний.
  - Пользователь может указать удобное время для получения уведомлений.

---

### **Дополнительные возможности**

1. **Обработка ошибок**:
   - Если что-то идет не так, бот отправляет сообщение: "Произошла ошибка. Попробуйте позже."

2. **Самопроверка**:
   - Для тарифа "Без проверки д/з" предусмотрена возможность самопроверки домашнего задания.

3. **Галерея домашних заданий**:
   - Пользователи могут просматривать выполненные домашние задания других участников.

4. **Многокурсовая поддержка**:
   - Пользователь может активировать несколько курсов одновременно и переключаться между ними.

5. **Вспомогательный режим курса**:
   - После завершения курса материалы остаются доступными для повторного просмотра.
### Оплата

Для оплаты доступа к урокам введите одно из кодовых слов:
- для тарифа "Без проверки д/з".
- для тарифа "С проверкой д/з".
- для тарифа "Личное сопровождение".

## Вклад

Если вы хотите внести свой вклад в развитие этого проекта, пожалуйста, следуйте этим шагам:

1. Сделайте форк репозитория.
2. Создайте новую ветку (`git checkout -b feature/new-feature`).
3. Внесите изменения и отправьте коммиты (`git commit -am 'Add new feature'`).
4. Отправьте запрос на слияние.

## Лицензия

Этот проект распространяется по лицензии MIT. Подробнее см. файл [LICENSE](LICENSE).

## Контакты

Если у вас есть вопросы или предложения, пожалуйста, свяжитесь со мной в тг https://t.me/Andreyjurievich или откройте issue в этом репозитории.

---

Спасибо за использование нашего бота! Мы надеемся, что он поможет вам!