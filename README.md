Easy Auto-presser like to hold any keys or mouse also can work as auto clicker guides rightly in the proggram
.exe in dist
(there is info from HELP (in Russian))
Автохолдер клавиш/кнопок мыши с биндами.

  F8 - ЭКСТРЕННАЯ ОСТАНОВКА всех задач и активных биндов (глобально).

ОБОЗНАЧЕНИЯ В КОМАНДАХ:
  <id>     номер задачи (число из `list`) или all (все задачи)
  <src>    клавиша-источник (например: f6, a, space, left)
  <dst>    целевая клавиша (например: a, space)
  <t>      время в секундах: 5, 1.4, или диапазон 1.4-1.7
  <файл>   имя JSON-файла (например: bb.json)
  <0|1>    0 = синтетические нажатия (из add) НЕ триггерят bind
           1 = синтетические нажатия ТОЖЕ триггерят bind

ЗАДАЧИ (автохолдер):
  add                        создать задачу (диалог: клавиша, держать, отпуск)
  list                       список всех задач (ID, клавиша, тайминги, статус)
  start  <id|all>            запустить задачу(и)
  stop   <id|all>            остановить задачу(и), клавиша отпускается
  pause  <id|all>            пауза (таймер замораживается)
  resume <id|all>            продолжить; остановленную задачу перезапускает
  remove <id|all>            удалить задачу(и)

ИЗМЕНЕНИЕ ЗАДАЧ:
  edit hold <id> [<t>]       изменить «держать»; без <t> — спросит интерактивно
  edit release <id> [<t>]    изменить «не держать»; без <t> — спросит

БИНДЫ:
  bind global <src> <dst>            ремап: нажал <src> — нажимается <dst>
  bind local <src> '<cmds>' <0|1>    нажал <src> — выполнить команды через запятую
  edit bind <src>                    изменить существующий бинд (интерактивно)
  unbind <src>                       удалить бинд для клавиши <src>
  binds                              список всех биндов

  Команды, доступные ВНУТРИ bind local '<cmds>':
    start <id|all> | stop <id|all> | pause <id|all> | resume <id|all>
    remove <id|all> | list | binds | unbind <src>
    edit hold <id> <t> | edit release <id> <t>
    wait <t>  (синонимы: sleep <t>, time.sleep(<t>))  пример: wait 1.4-1.7

ПРОФИЛИ:
  save <файл>                сохранить задачи + бинды в JSON
  load <файл>                загрузить из JSON (старые профили совместимы)

ПРОЧЕЕ:
  help                       эта справка
  quit / exit / q            выход (все задачи останавливаются)

ПРИМЕРЫ:
  add                                       → создать задачу
  edit hold 1 1.4-1.7                       → держать случайно 1.4..1.7 сек
  edit release 1 0.5                        → пауза 0.5 сек
  bind global f6 a                          → f6 превращается в a
  bind local f7 'stop all, wait 5, resume all' 0
  bind local f9 'edit hold 1 2-3' 0         → f9 меняет hold первой задачи
  edit bind f7                              → перенастроить бинд f7
  save bb.json
