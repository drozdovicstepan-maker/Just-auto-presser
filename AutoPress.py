#!/usr/bin/env python3
"""
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
"""
import json
import random
import re
import sys
import threading
import time

try:
    from pynput.keyboard import (Controller as KeyboardController, Key, KeyCode,
                                 Listener as KeyboardListener)
    from pynput.mouse import Controller as MouseController, Button
except ImportError:
    print("Установите pynput:  pip install pynput")
    sys.exit(1)

keyboard = KeyboardController()
mouse = MouseController()

SPECIAL_KEYS = {
    'space': Key.space, 'enter': Key.enter, 'tab': Key.tab,
    'shift': Key.shift, 'ctrl': Key.ctrl, 'alt': Key.alt,
    'esc': Key.esc, 'backspace': Key.backspace,
    'up': Key.up, 'down': Key.down, 'left_arrow': Key.left,
    'right_arrow': Key.right,
    'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
    'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f9': Key.f9,
    'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
}
MOUSE_BUTTONS = {'left': Button.left, 'right': Button.right, 'middle': Button.middle}

TIME_RE = re.compile(r'^\s*([\d.]+)(?:\s*-\s*([\d.]+))?\s*$')
WAIT_RE = re.compile(
    r'^(?:wait|sleep|time\.sleep)\s*\(?\s*([\d.]+(?:\s*-\s*[\d.]+)?)\s*\)?\s*$',
    re.IGNORECASE)


# ---------- утилиты ----------
def parse_time(s):
    m = TIME_RE.match(s.replace(',', '.').strip())
    if not m:
        raise ValueError(f"неверное время: {s!r}")
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    if lo > hi:
        lo, hi = hi, lo
    return (lo, hi)


def pick(rng):
    lo, hi = rng
    return lo if lo == hi else random.uniform(lo, hi)


def fmt_range(r):
    lo, hi = r
    return f"{lo:.2f}" if lo == hi else f"{lo:.2f}-{hi:.2f}"


def key_to_name(key):
    if isinstance(key, Key):
        return key.name
    if isinstance(key, KeyCode) and key.char:
        return key.char.lower()
    return None


def resolve_key(name):
    return SPECIAL_KEYS.get(name, name)


# ---------- синтетические события ----------
_synth_lock = threading.Lock()
_synth_events = set()


def _is_synth(name):
    with _synth_lock:
        return name in _synth_events


def _synthetic_press(name, fn):
    with _synth_lock:
        _synth_events.add(name)
    try:
        fn()
    finally:
        with _synth_lock:
            _synth_events.discard(name)


_emergency = threading.Event()
_holder = None
_held_remaps = {}


# ==================== Задача ====================
class Task:
    def __init__(self, tid, target, hold, release, is_mouse=False):
        self.id = tid
        self.target = target
        self.hold = hold
        self.release = release
        self.is_mouse = is_mouse
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self.thread = None
        self.paused = False

    def _key(self):
        return resolve_key(self.target)

    def _press(self):
        if self.is_mouse:
            mouse.press(MOUSE_BUTTONS[self.target])
        else:
            _synthetic_press(self.target, lambda: keyboard.press(self._key()))

    def _release_key(self):
        try:
            if self.is_mouse:
                mouse.release(MOUSE_BUTTONS[self.target])
            else:
                _synthetic_press(self.target, lambda: keyboard.release(self._key()))
        except Exception:
            pass

    def _sleep(self, duration):
        end = time.time() + duration
        while True:
            if self._stop.is_set():
                return False
            if not self._pause.is_set():
                pstart = time.time()
                while not self._pause.wait(timeout=0.5):
                    if self._stop.is_set():
                        return False
                end += time.time() - pstart
            now = time.time()
            if now >= end:
                return True
            time.sleep(min(0.02, end - now))

    def _run(self):
        try:
            while not self._stop.is_set():
                if not self._pause.wait(timeout=0.5):
                    continue
                self._press()
                if not self._sleep(pick(self.hold)):
                    break
                self._release_key()
                if not self._sleep(pick(self.release)):
                    break
        finally:
            self._release_key()

    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        self._stop.clear()
        self._pause.set()
        self.paused = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self._stop.set()
        self._pause.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def pause(self):
        self.paused = True
        self._pause.clear()

    def resume(self):
        if not self.is_running():
            self.start()
            return
        self.paused = False
        self._pause.set()

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def to_dict(self):
        return {'id': self.id, 'target': self.target,
                'hold': list(self.hold), 'release': list(self.release),
                'is_mouse': self.is_mouse}

    @classmethod
    def from_dict(cls, d):
        def norm(v):
            if isinstance(v, (list, tuple)):
                return (float(v[0]), float(v[1]))
            return (float(v), float(v))
        return cls(d['id'], d['target'], norm(d['hold']), norm(d['release']),
                   d.get('is_mouse', False))


# ==================== Холдер ====================
class Holder:
    def __init__(self):
        self.tasks = {}
        self.next_id = 1
        self.global_binds = {}
        self.local_binds = {}

    def find(self, arg):
        try:
            tid = int(arg)
        except ValueError:
            print("Неверный ID")
            return None
        if tid not in self.tasks:
            print(f"Нет задачи #{tid}")
            return None
        return self.tasks[tid]

    # ---------- add/list ----------
    def cmd_add(self):
        print("\n--- Новая задача (время можно диапазоном: 1.4-1.7) ---")
        print("Обычные клавиши: a, w, 1 ...")
        print("Спец-клавиши:", ', '.join(SPECIAL_KEYS))
        print("Кнопки мыши:", ', '.join(MOUSE_BUTTONS))
        target = input("Клавиша/кнопка: ").strip().lower()
        if target == 'f8':
            print("F8 зарезервирована под экстренную остановку")
            return
        if target in MOUSE_BUTTONS:
            is_mouse = True
        elif target in SPECIAL_KEYS or len(target) == 1:
            is_mouse = False
        else:
            print("Неизвестная клавиша/кнопка")
            return
        try:
            hold = parse_time(input("Держать (сек): "))
            release = parse_time(input("Не держать (сек): "))
        except ValueError as e:
            print(f"Ошибка: {e}")
            return
        if hold[0] <= 0 or release[0] < 0:
            print("Время должно быть положительным")
            return
        tid = self.next_id
        self.tasks[tid] = Task(tid, target, hold, release, is_mouse)
        self.next_id += 1
        print(f"Задача #{tid} создана. Запуск: start {tid}")

    def cmd_list(self):
        if not self.tasks:
            print("Задач нет")
            return
        print(f"\n{'ID':>3} | {'Кнопка':<10} | {'Держать':>14} | {'Отпуск':>14} | Статус")
        print("-" * 66)
        for t in self.tasks.values():
            if t.is_running():
                status = "paused" if t.paused else "running"
            else:
                status = "stopped"
            print(f"{t.id:>3} | {t.target:<10} | {fmt_range(t.hold):>14} | "
                  f"{fmt_range(t.release):>14} | {status}")

    # ---------- управление задачами ----------
    def cmd_start(self, arg):
        if arg == 'all':
            for t in list(self.tasks.values()):
                t.start()
            print("Все задачи запущены")
        else:
            t = self.find(arg)
            if t:
                t.start()
                print(f"#{t.id} запущена")

    def cmd_stop(self, arg):
        if arg == 'all':
            for t in list(self.tasks.values()):
                t.stop()
            print("Все остановлены")
        else:
            t = self.find(arg)
            if t:
                t.stop()
                print(f"#{t.id} остановлена")

    def cmd_pause(self, arg):
        if arg == 'all':
            for t in list(self.tasks.values()):
                t.pause()
            print("Все на паузе")
        else:
            t = self.find(arg)
            if t:
                t.pause()
                print(f"#{t.id} на паузе")

    def cmd_resume(self, arg):
        if arg == 'all':
            for t in list(self.tasks.values()):
                t.resume()
            print("Все продолжены")
        else:
            t = self.find(arg)
            if t:
                t.resume()
                print(f"#{t.id} продолжена")

    def cmd_remove(self, arg):
        if arg == 'all':
            for t in list(self.tasks.values()):
                t.stop()
            self.tasks.clear()
            print("Все задачи удалены")
            return
        t = self.find(arg)
        if t:
            t.stop()
            del self.tasks[t.id]
            print(f"#{t.id} удалена")

    # ---------- edit ----------
    def cmd_edit(self, args_str, interactive=True):
        parts = args_str.split(maxsplit=1)
        if not parts:
            print("Формат: edit bind <src> | edit hold <id> [<t>] | edit release <id> [<t>]")
            return
        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ''

        # ---- edit bind ----
        if sub == 'bind':
            if not interactive:
                print("edit bind доступен только из консоли (из bind используй bind ...)")
                return
            src = rest.strip().lower()
            if not src:
                print("Формат: edit bind <src>")
                return
            found = False
            if src in self.global_binds:
                found = True
                cur = self.global_binds[src]
                print(f"Текущий global: {src} -> {cur}")
                new_dst = input(f"Новая цель (Enter — оставить '{cur}'): ").strip().lower()
                if new_dst:
                    if new_dst == 'f8':
                        print("F8 зарезервирована")
                    else:
                        self.global_binds[src] = new_dst
                        print(f"global {src} -> {new_dst}")
            if src in self.local_binds:
                found = True
                b = self.local_binds[src]
                print(f"Текущий local: {src} -> {b['commands']} "
                      f"(синтетика: {b['allow_synthetic']})")
                new_cmds = input("Команды через запятую (Enter — оставить): ").strip()
                if new_cmds:
                    cmds = [c.strip() for c in new_cmds.split(',') if c.strip()]
                    if cmds:
                        b['commands'] = cmds
                new_flag = input(
                    f"Флаг 0/1 (Enter — оставить {b['allow_synthetic']}): ").strip()
                if new_flag in ('0', '1'):
                    b['allow_synthetic'] = int(new_flag)
                print(f"local {src} обновлён")
            if not found:
                print(f"Нет бинда для {src}. Создать: bind global/local ...")

        # ---- edit hold / edit release ----
        elif sub in ('hold', 'release'):
            pieces = rest.split(maxsplit=1)
            if not pieces:
                print(f"Формат: edit {sub} <id> [<t>]")
                return
            t = self.find(pieces[0])
            if not t:
                return
            label = 'держать' if sub == 'hold' else 'не держать'
            cur = t.hold if sub == 'hold' else t.release
            if len(pieces) > 1:
                val = pieces[1].strip()
            else:
                print(f"#{t.id} сейчас {label}: {fmt_range(cur)}")
                val = input(f"Новое значение ({label}, можно 1.4-1.7): ").strip()
            if not val:
                return
            try:
                rng = parse_time(val)
            except ValueError as e:
                print(f"Ошибка: {e}")
                return
            if rng[0] < 0 or (sub == 'hold' and rng[0] <= 0):
                print("Время должно быть положительным")
                return
            if sub == 'hold':
                t.hold = rng
            else:
                t.release = rng
            print(f"#{t.id} {label}: {fmt_range(rng)}")
        else:
            print("Неизвестная подкоманда. Формат: edit bind|hold|release ...")

    # ---------- bind ----------
    def _parse_bind(self, text):
        m = re.match(r'^(global|local)\s+(.+)$', text.strip(), re.IGNORECASE)
        if not m:
            return None
        btype = m.group(1).lower()
        rest = m.group(2).strip()
        if btype == 'global':
            parts = rest.split()
            if len(parts) != 2:
                return None
            return ('global', parts[0].lower(), parts[1].lower())
        m2 = re.match(r"^(\S+)\s+(['\"])(.*?)\2\s+([01])\s*$", rest, re.DOTALL)
        if not m2:
            return None
        return ('local', m2.group(1).lower(), m2.group(3), int(m2.group(4)))

    def cmd_bind(self, args_str):
        parsed = self._parse_bind(args_str)
        if parsed is None:
            print("Формат: bind global <src> <dst>")
            print("        bind local <src> '<cmds>' <0|1>")
            print("Пример: bind global f6 a")
            print("        bind local f7 'stop all, wait 5, resume all' 0")
            return
        if parsed[0] == 'global':
            _, src, dst = parsed
            if src == 'f8' or dst == 'f8':
                print("F8 зарезервирована")
                return
            self.global_binds[src] = dst
            print(f"global bind: {src} -> {dst}")
        else:
            _, src, cmds_text, flag = parsed
            if src == 'f8':
                print("F8 зарезервирована")
                return
            cmds = [c.strip() for c in cmds_text.split(',') if c.strip()]
            if not cmds:
                print("Пустой список команд")
                return
            self.local_binds[src] = {'commands': cmds, 'allow_synthetic': flag}
            mode = "вкл" if flag else "выкл"
            print(f"local bind: {src} -> {cmds} (синтетические: {mode})")

    def cmd_unbind(self, arg):
        src = arg.lower()
        removed = False
        if src in self.global_binds:
            del self.global_binds[src]
            removed = True
        if src in self.local_binds:
            del self.local_binds[src]
            removed = True
        print(f"Бинд {src} удалён" if removed else f"Нет бинда {src}")

    def cmd_binds(self):
        if not self.global_binds and not self.local_binds:
            print("Биндов нет")
            return
        if self.global_binds:
            print("Global:")
            for s, d in self.global_binds.items():
                print(f"  {s} -> {d}")
        if self.local_binds:
            print("Local:")
            for s, b in self.local_binds.items():
                mode = "on" if b['allow_synthetic'] else "off"
                print(f"  {s} -> [{mode}] {b['commands']}")

    # ---------- save/load ----------
    def cmd_save(self, fname):
        data = {
            'next_id': self.next_id,
            'tasks': [t.to_dict() for t in self.tasks.values()],
            'global_binds': dict(self.global_binds),
            'local_binds': {k: dict(v) for k, v in self.local_binds.items()},
        }
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Сохранено в {fname}")
        except Exception as e:
            print(f"Ошибка: {e}")

    def cmd_load(self, fname):
        try:
            with open(fname, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки: {e}")
            return
        for t in list(self.tasks.values()):
            t.stop()
        self.tasks.clear()
        self.global_binds.clear()
        self.local_binds.clear()
        for d in data.get('tasks', []):
            self.tasks[d['id']] = Task.from_dict(d)
        self.next_id = data.get('next_id', max(self.tasks, default=0) + 1)
        self.global_binds.update(data.get('global_binds', {}))
        for k, v in data.get('local_binds', {}).items():
            self.local_binds[k] = {
                'commands': list(v.get('commands', [])),
                'allow_synthetic': int(v.get('allow_synthetic', 0)),
            }
        print(f"Загружено: задач {len(self.tasks)}, биндов "
              f"{len(self.global_binds) + len(self.local_binds)}")

    # ---------- исполнение bind ----------
    def execute_bind(self, cmds):
        _emergency.clear()
        for raw in cmds:
            if _emergency.is_set():
                print("[bind] прервано (F8)")
                return
            try:
                self._run_bind_one(raw)
            except Exception as e:
                print(f"[bind] ошибка в '{raw}': {e}")
                return

    def _run_bind_one(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        m = WAIT_RE.match(cmd)
        if m:
            self._wait(pick(parse_time(m.group(1))))
            return
        parts = cmd.split()
        name = parts[0].lower()
        args = parts[1:]
        if name in ('start', 'stop', 'pause', 'resume', 'remove') and args:
            getattr(self, f'cmd_{name}')(args[0])
        elif name == 'edit' and args:
            self.cmd_edit(' '.join(args), interactive=False)
        elif name == 'list':
            self.cmd_list()
        elif name == 'unbind' and args:
            self.cmd_unbind(args[0])
        elif name == 'binds':
            self.cmd_binds()
        else:
            raise ValueError(f"неизвестная команда {cmd!r}")

    def _wait(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if _emergency.is_set():
                return
            time.sleep(min(0.1, end - time.time()))


# ==================== Слушатель ====================
def on_press(key):
    name = key_to_name(key)
    if name is None:
        return True
    synth = _is_synth(name)

    if name == 'f8' and not synth:
        _emergency.set()
        snap = list(_holder.tasks.values())
        for t in snap:
            t.stop()
        print(f"\n[F8] ЭКСТРЕННЫЙ СТОП: {len(snap)} задач")
        return True

    if not synth and name in _holder.global_binds and name not in _held_remaps:
        dst = _holder.global_binds[name]
        _held_remaps[name] = dst
        _synthetic_press(dst, lambda: keyboard.press(resolve_key(dst)))

    if name in _holder.local_binds:
        b = _holder.local_binds[name]
        if b['allow_synthetic'] or not synth:
            threading.Thread(target=_holder.execute_bind, args=(b['commands'],),
                             daemon=True).start()
    return True


def on_release(key):
    name = key_to_name(key)
    if name is None or _is_synth(name):
        return True
    if name in _held_remaps:
        dst = _held_remaps.pop(name)
        _synthetic_press(dst, lambda: keyboard.release(resolve_key(dst)))
    return True


# ==================== CLI ====================
def main():
    global _holder
    _holder = Holder()

    listener = KeyboardListener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    print("=" * 66)
    print(" Автохолдер + бинды.  F8 — экстренный стоп (работает везде).")
    print(" Время можно диапазоном: 1.4-1.7.  'help' — подробная справка.")
    print("=" * 66)

    try:
        while True:
            try:
                line = input("\n> ").strip()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else None

            try:
                if cmd == 'help':
                    print(__doc__)
                elif cmd == 'add':
                    _holder.cmd_add()
                elif cmd == 'list':
                    _holder.cmd_list()
                elif cmd in ('start', 'stop', 'pause', 'resume', 'remove') and arg:
                    getattr(_holder, f'cmd_{cmd}')(arg)
                elif cmd == 'edit' and arg:
                    _holder.cmd_edit(arg)
                elif cmd == 'bind' and arg:
                    _holder.cmd_bind(arg)
                elif cmd == 'unbind' and arg:
                    _holder.cmd_unbind(arg)
                elif cmd == 'binds':
                    _holder.cmd_binds()
                elif cmd == 'save' and arg:
                    _holder.cmd_save(arg)
                elif cmd == 'load' and arg:
                    _holder.cmd_load(arg)
                elif cmd in ('quit', 'exit', 'q'):
                    break
                else:
                    print("Неизвестная команда. 'help' — справка.")
            except Exception as e:
                print(f"Ошибка: {e}")
    except KeyboardInterrupt:
        print("\nПрервано")
    finally:
        for t in list(_holder.tasks.values()):
            t.stop()
        print("Все задачи остановлены. Выход.")


if __name__ == '__main__':
    main()
