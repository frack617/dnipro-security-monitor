# Незалежний контроль запусків

Це окремий новий Apps Script, а не зміна існуючого резервного скрипту.
Він перевіряє стан GitHub кожні 5 хвилин. Якщо успішний збір старший за 25 хвилин
або після 08:00 ще не відмічена доставка за сьогодні, він запускає collect.yml.
Пауза між прийнятими повторними запусками — не менше 10 хвилин.
Скрипт не викликає Gemini, не формує довідок і не надсилає Telegram-повідомлень.
Перевірка дати в збирачі запобігає повторній звичайній довідці.

1. На https://github.com/settings/personal-access-tokens створіть fine-grained token.
   Repository access: Only select repositories → dnipro-security-monitor.
   Repository permissions: Actions → Read and write. Інших прав запису не потрібно.
2. Відкрийте https://script.google.com і створіть НОВИЙ проєкт.
   Вставте в Code.gs вміст файла scheduler/Code.gs з цього архіву.
3. Project Settings → Script properties → Add script property:
   назва GITHUB_ACTIONS_TOKEN, значення — створений токен. Не вставляйте токен у код,
   репозиторій чи чат. Збережіть.
4. У редакторі виберіть installMonitorWatchdog, натисніть Run і надайте дозволи
   своєму скрипту. Перевірте, що є один тригер monitorWatchdog кожні 5 хвилин.

Продовження токена після закінчення строку дії та помилки Apps Script видно в
Executions цього нового проєкту. Установка ZIP сама по собі тригера не створює.
Apps Script і GitHub також можуть затримувати запуск: це додатковий незалежний
контроль, а не гарантія доставки точно о 08:00 або повноцінний серверний SLA.
