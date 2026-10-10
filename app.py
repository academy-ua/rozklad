# Генератор розкладу академії — один файл.
# Запуск:  pip install streamlit pandas xlsxwriter ortools
#          streamlit run rozklad_app.py
"""Ядро генерації розкладу: модель по реальних тижнях семестру.

Кожна пара — окрема змінна (дисципліна, тиждень, день, пара). Тому заборона
вікон, накладок і обмеження викладачів перевіряються саме в тих тижнях,
які побачать студенти й викладачі.
"""
import math
import re
from collections import defaultdict

from ortools.sat.python.cp_model import CpModel, CpSolver, OPTIMAL, FEASIBLE

DAY_NAMES = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]
AUTO_ROOM = "✨ Автоматичний підбір з фонду"
ONLINE = "ОНЛАЙН"
NOT_IN_POOL = {"ОНЛАЙН", "СПОРТЗАЛ"}  # не беруть участі в автоматичному підборі


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    try:
        return [_clean(x) for x in v if _clean(x)]
    except TypeError:
        return []


def slot_numbers(items, slots_count):
    """Перетворює ['0 пара (...)', 'Всі пари'] на множину номерів пар."""
    items = _as_list(items)
    if any("Всі пари" in i for i in items):
        return set(range(slots_count))
    out = set()
    for i in items:
        m = re.match(r"\s*(\d+)\s*пара", i)
        if m and int(m.group(1)) < slots_count:
            out.add(int(m.group(1)))
    return out


def parse_weeks(text, upto):
    """'6-9' / '6,7,8' / '6-7, 12' -> {6, 7, 8, 9} (номери тижнів з 1, не більше upto)."""
    out = set()
    text = re.sub(r"\s*[-–—]\s*", "-", _clean(text))
    for part in re.split(r"[,;\s]+", text):
        m = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", part) or re.fullmatch(r"(\d+)", part)
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.lastindex == 2 else a
        out.update(i for i in range(min(a, b), max(a, b) + 1) if 1 <= i <= upto)
    return out


def weeks_text(idx0):
    """[0,1,2,5,6] -> '1–3, 6–7' (вхід — індекси з 0)."""
    nums = sorted(i + 1 for i in idx0)
    parts, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            parts.append(f"{start}" if start == n else f"{start}–{n}")
            start = None
    return ", ".join(parts)


def prepare(cfg, days_count, slots_count, max_weeks):
    """Нормалізує дані й повертає (specs, довідники, попередження)."""
    warnings = []
    teachers = [t.strip() for t in _clean(cfg.get("teachers")).split("\n") if t.strip()]
    rooms = [r.strip() for r in _clean(cfg.get("rooms")).split("\n") if r.strip()]
    days = DAY_NAMES[:days_count]

    groups = {}
    for g in cfg.get("groups", []):
        name = _clean(g.get("Група"))
        if not name:
            continue
        try:
            w = int(float(g.get("Кількість тижнів") or max_weeks))
        except (TypeError, ValueError):
            w = max_weeks
        practice = _clean(g.get("День практики"))
        w = min(w, max_weeks)
        pw = parse_weeks(g.get("Тижні практики"), w)  # номери з 1
        study = [i for i in range(w) if i + 1 not in pw]  # індекси з 0
        if not study:
            warnings.append(f"Група {name}: усі тижні зайняті практикою — занять не буде.")
        groups[name] = {
            "weeks": w,
            "practice_weeks": pw,
            "wset": study,
            "practice_day": days.index(practice) if practice in days else None,
        }

    # недоступність викладачів: teacher -> {(day, slot)}
    blocked = defaultdict(set)
    for lim in cfg.get("limits", []):
        t = _clean(lim.get("Викладач"))
        if not t:
            continue
        d = _clean(lim.get("День тижня"))
        tdays = range(days_count) if d == "Всі дні" else ([days.index(d)] if d in days else [])
        for di in tdays:
            for sl in slot_numbers(lim.get("Недоступні пари"), slots_count):
                blocked[t].add((di, sl))

    specs = []
    for idx, row in enumerate(cfg.get("curriculum", [])):
        grps = _as_list(row.get("Групи"))
        subj = _clean(row.get("Предмет"))
        teacher = _clean(row.get("Викладач"))
        if not grps or not subj:
            continue
        label = f"«{subj}» ({', '.join(grps)})"
        unknown = [g for g in grps if g not in groups]
        if unknown:
            warnings.append(f"{label}: невідомі групи {', '.join(unknown)} — рядок пропущено.")
            continue
        if teacher and teacher not in teachers:
            warnings.append(f"{label}: викладача «{teacher}» немає в списку викладачів.")
        try:
            hours = float(row.get("Годин на семестр") or 0)
        except (TypeError, ValueError):
            hours = 0
        pairs = math.ceil(hours / 2)
        if pairs <= 0:
            warnings.append(f"{label}: не вказано години — рядок пропущено.")
            continue

        fmt = _clean(row.get("Формат")) or "Очно"
        room = _clean(row.get("Аудиторія"))
        online = fmt == "Онлайн" or room.upper() == ONLINE
        if fmt != "Онлайн" and room.upper() == ONLINE:
            warnings.append(f"{label}: формат «Очно», але аудиторія ОНЛАЙН — вважаю заняття онлайн.")
        if online:
            room_kind, room_name = "online", ONLINE
        elif not room or room == AUTO_ROOM:
            room_kind, room_name = "auto", None
        else:
            room_kind, room_name = "fixed", room
            if room not in rooms:
                warnings.append(f"{label}: аудиторії «{room}» немає у фонді.")

        # тижні, коли навчаються всі групи рядка
        sets = [set(groups[g]["wset"]) for g in grps]
        wset = sorted(set.intersection(*sets))
        if not wset:
            warnings.append(f"{label}: немає жодного тижня, коли навчаються всі групи — рядок пропущено.")
            continue
        if len(grps) > 1 and any(s != sets[0] for s in sets):
            warnings.append(f"{label}: у груп потоку різні навчальні тижні, тому спільні заняття "
                            f"ставлю лише в тижні, коли навчаються всі ({len(wset)} тиж.: {weeks_text(wset)}). "
                            f"Окремі заняття кожної групи йдуть за її власними тижнями.")
        weeks = len(wset)
        lo, hi = pairs // weeks, math.ceil(pairs / weeks)

        # дозволені (день, пара) з урахуванням викладача і днів практики
        bad_days = {groups[g]["practice_day"] for g in grps} - {None}
        allowed = [(d, sl) for d in range(days_count) for sl in range(slots_count)
                   if d not in bad_days and (d, sl) not in blocked.get(teacher, set())]
        if hi > len(allowed):
            warnings.append(f"{label}: потрібно {hi} пар на тиждень, а доступно лише {len(allowed)} місць.")

        specs.append({
            "id": len(specs), "row": idx, "groups": grps, "subject": subj, "teacher": teacher,
            "online": online, "room_kind": room_kind, "room": room_name,
            "is_stream": _clean(row.get("Потокова лекція?")) == "Так",
            "pairs": pairs, "weeks": weeks, "wset": wset, "lo": lo, "hi": hi, "allowed": allowed,
        })

    pool = [r for r in rooms if r.upper() not in NOT_IN_POOL]
    return specs, {"groups": groups, "teachers": teachers, "rooms": rooms, "pool": pool,
                   "blocked": blocked, "days": days}, warnings


def generate(cfg, days_count=5, slots_count=5, max_weeks=15, max_per_day=4, min_per_day=2,
             lectures_first=True, stable=True, time_limit=60, workers=8, fixed=None):
    """Повертає (records, warnings, error).

    stable=True — кожна дисципліна має постійні місця, однакові щотижня,
    і не більше одного «додаткового» місця для тижнів, де потрібна ще одна пара.
    stable=False — вільний режим: місця можуть змінюватися від тижня до тижня.
    fixed — уже розставлені пари (інших груп): їхні викладачі й аудиторії зайняті.
    """
    specs, ref, warnings = prepare(cfg, days_count, slots_count, max_weeks)
    if not specs:
        return None, warnings, "Навчальний план порожній."
    groups, pool = ref["groups"], ref["pool"]
    max_per_day = min(max_per_day or slots_count, slots_count)
    min_per_day = max(1, min(min_per_day or 1, max_per_day))

    busy_t, busy_r, pool_used = set(), set(), defaultdict(int)
    for r in fixed or []:
        c = (r["week"] - 1, r["day_idx"], r["slot_idx"])
        if r["teacher"]:
            busy_t.add((r["teacher"], *c))
        if not r["online"]:
            busy_r.add((r["room"], *c))
            if r["room"] in pool:
                pool_used[c] += 1

    m = CpModel()
    x = {}
    for s in specs:
        for w in s["wset"]:
            for d, sl in s["allowed"]:
                v = m.NewBoolVar(f"x{s['id']}_{w}_{d}_{sl}")
                x[s["id"], w, d, sl] = v
                if (s["teacher"], w, d, sl) in busy_t or \
                        (s["room_kind"] == "fixed" and (s["room"], w, d, sl) in busy_r):
                    m.Add(v == 0)

    by_spec_week = defaultdict(list)
    by_cell = defaultdict(list)  # (w,d,sl) -> [(spec, var)]
    for (sid, w, d, sl), v in x.items():
        by_spec_week[sid, w].append(v)
        by_cell[w, d, sl].append((specs[sid], v))

    # 1. Години: усього рівно pairs, у кожному тижні рівномірно (lo..hi)
    for s in specs:
        m.Add(sum(sum(by_spec_week[s["id"], w]) for w in s["wset"]) == s["pairs"])
        for w in s["wset"]:
            wk = sum(by_spec_week[s["id"], w])
            if s["lo"] > 0:
                m.Add(wk >= s["lo"])
            m.Add(wk <= s["hi"])

    # 1а. Стабільність: постійні місця (base) + одне додаткове місце (extra)
    if stable:
        for s in specs:
            base = {c: m.NewBoolVar("") for c in s["allowed"]} if s["lo"] > 0 else {}
            extra = {c: m.NewBoolVar("") for c in s["allowed"]} if s["hi"] > s["lo"] else {}
            if base:
                m.Add(sum(base.values()) == s["lo"])
            if extra:
                # «рідкісна» дисципліна (менше пари на тиждень) може мати два постійні місця,
                # щоб краще поєднуватися з іншими і не лишати групі днів з однією парою
                if s["lo"] == 0:
                    m.Add(sum(extra.values()) >= 1)
                    m.Add(sum(extra.values()) <= 2)
                else:
                    m.Add(sum(extra.values()) == 1)
            for c in s["allowed"]:
                b, e = base.get(c, 0), extra.get(c, 0)
                if base and extra:
                    m.Add(b + e <= 1)
                for w in s["wset"]:
                    v = x[s["id"], w, *c]
                    if base:
                        m.Add(v >= b)
                    m.Add(v <= b + e)

    # 2. Накладки: група, викладач, аудиторія
    grp_cell = {}
    for (w, d, sl), items in by_cell.items():
        per_g, per_t, per_r = defaultdict(list), defaultdict(list), defaultdict(list)
        auto, pool_fixed = [], []
        for s, v in items:
            for g in s["groups"]:
                per_g[g].append(v)
            if s["teacher"]:
                per_t[s["teacher"]].append(v)
            if s["room_kind"] == "fixed":
                per_r[s["room"]].append(v)
                if s["room"] in pool:
                    pool_fixed.append(v)
            elif s["room_kind"] == "auto":
                auto.append(v)
        for g, vs in per_g.items():
            if len(vs) > 1:
                m.Add(sum(vs) <= 1)
            grp_cell[g, w, d, sl] = vs
        for vs in per_t.values():
            if len(vs) > 1:
                m.Add(sum(vs) <= 1)
        for vs in per_r.values():
            if len(vs) > 1:
                m.Add(sum(vs) <= 1)
        if auto:
            # Кожна «автоматична» пара бере будь-яку вільну аудиторію фонду,
            # тож досить, щоб їх було не більше, ніж вільних аудиторій.
            m.Add(sum(auto) + sum(pool_fixed) <= len(pool) - pool_used[w, d, sl])

    # 3. Без вікон у груп; пар на день — від min_per_day до max_per_day.
    #    Менше за мінімум можна лише тоді, коли за весь тиждень у групи менше пар.
    for g, info in groups.items():
        for w in info["wset"]:
            week_vars = [v for d in range(days_count) for sl in range(slots_count)
                         for v in grp_cell.get((g, w, d, sl), [])]
            for d in range(days_count):
                occ = [sum(grp_cell.get((g, w, d, sl), [])) for sl in range(slots_count)]
                has = [bool(grp_cell.get((g, w, d, sl))) for sl in range(slots_count)]
                if sum(has) == 0:
                    continue
                day_total = sum(occ)
                if max_per_day < sum(has):
                    m.Add(day_total <= max_per_day)
                if min_per_day > 1:
                    on = m.NewBoolVar("")      # у групи є пари цього дня
                    short = m.NewBoolVar("")   # пар менше за мінімум (дозволено лише в «малий» тиждень)
                    m.Add(day_total <= slots_count * on)
                    m.Add(day_total >= on)
                    m.Add(day_total >= min_per_day * on - min_per_day * short)
                    big = len(week_vars)
                    m.Add(sum(week_vars) + big * short <= (min_per_day - 1) + big)
                for a in range(slots_count):
                    for c in range(a + 2, slots_count):
                        if not (has[a] and has[c]):
                            continue
                        for b in range(a + 1, c):
                            m.Add(occ[a] + occ[c] <= 1 + occ[b])

    # 4. Лекція раніше практичних: практичне з тієї самої дисципліни не повинно йти
    #    в тижні, коли ще не було жодної лекції потоку. Це сильне побажання
    #    (великий штраф): розв'язувач дотримує його завжди, коли це можливо,
    #    а перевірка після генерації показує кожне порушення.
    obj = []
    if lectures_first:
        key = defaultdict(list)
        for s in specs:
            key[s["subject"].lower(), s["teacher"]].append(s)
        for lst in key.values():
            lects = [s for s in lst if s["is_stream"]]
            for p in (s for s in lst if not s["is_stream"]):
                lect = next((l for l in lects if set(p["groups"]) & set(l["groups"])), None)
                if not lect:
                    continue
                for w in p["wset"]:
                    cum = [v for ww in lect["wset"] if ww <= w for v in by_spec_week[lect["id"], ww]]
                    late = m.NewBoolVar("")
                    m.Add(sum(by_spec_week[p["id"], w]) <= p["hi"] * sum(cum) + p["hi"] * late)
                    obj.append(1000 * late)

    # --- Побажання (штрафи) ---
    # а) у вільному режимі — штраф за кожне нове місце дисципліни
    for s in ([] if stable else specs):
        for d, sl in s["allowed"]:
            u = m.NewBoolVar(f"u{s['id']}_{d}_{sl}")
            for w in s["wset"]:
                m.Add(u >= x[s["id"], w, d, sl])
            obj.append(10 * u)
    # б) менше днів приїзду для викладача і без днів з однією парою
    per_tday = defaultdict(list)
    for (sid, w, d, sl), v in x.items():
        t = specs[sid]["teacher"]
        if t:
            per_tday[t, w, d].append(v)
    for (t, w, d), vs in per_tday.items():
        day = m.NewBoolVar(f"td_{w}_{d}")
        for v in vs:
            m.Add(day >= v)
        single = m.NewBoolVar(f"ts_{w}_{d}")
        m.Add(single >= 2 * day - sum(vs))  # 1, якщо пара за день рівно одна
        obj.append(3 * day)
        obj.append(4 * single)

    m.Minimize(sum(obj))
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = workers
    status = solver.Solve(m)
    if status not in (OPTIMAL, FEASIBLE):
        return None, warnings, ("Розклад не знайдено: обмеження несумісні або бракує часу. "
                                "Перевір попередження нижче, збільш час пошуку чи пар на день.")

    # --- Розгортання і підбір аудиторій ---
    chosen = sorted((k for k, v in x.items() if solver.Value(v) == 1), key=lambda k: (k[1], k[2], k[3]))
    records = []
    taken = defaultdict(set)
    for r in fixed or []:
        if not r["online"]:
            taken[r["week"] - 1, r["day_idx"], r["slot_idx"]].add(r["room"])
    last_room = {}
    for sid, w, d, sl in chosen:
        s = specs[sid]
        if s["room_kind"] == "fixed":
            taken[w, d, sl].add(s["room"])
    for sid, w, d, sl in chosen:
        s = specs[sid]
        room = s["room"]
        if s["room_kind"] == "auto":
            free = [r for r in pool if r not in taken[w, d, sl]]
            room = last_room.get(sid) if last_room.get(sid) in free else (free[0] if free else "?")
            taken[w, d, sl].add(room)
            last_room[sid] = room
        records.append({
            "week": w + 1, "day_idx": d, "day": ref["days"][d], "slot_idx": sl,
            "groups": s["groups"], "subject": s["subject"], "teacher": s["teacher"],
            "room": room, "online": s["online"], "is_stream": s["is_stream"],
        })
    status_txt = "оптимальний" if status == OPTIMAL else "допустимий (не обов'язково найкращий)"
    warnings.insert(0, f"Знайдено розклад: {status_txt}.")
    return records, warnings, None


def clusters(cfg):
    """Групи, пов'язані спільними дисциплінами (потоками), — одна частина."""
    par = {}

    def find(a):
        while par.setdefault(a, a) != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for row in cfg.get("curriculum", []):
        gs = _as_list(row.get("Групи"))
        for g in gs[1:]:
            par[find(g)] = find(gs[0])
        for g in gs[:1]:
            find(g)
    out = defaultdict(set)
    for g in list(par):
        out[find(g)].add(g)
    return list(out.values())


def generate_by_parts(cfg, time_limit=120, progress=None, **kw):
    """Розв'язує частинами: спершу найнавантаженіші групи, далі решту
    з урахуванням уже зайнятих викладачів і аудиторій. Якщо якась частина
    не складається, ставить її першою і пробує знову."""
    rows = cfg.get("curriculum", [])
    parts = clusters(cfg)

    def load(gs):
        return sum(float(r.get("Годин на семестр") or 0)
                   for r in rows if set(_as_list(r.get("Групи"))) & gs)

    order = sorted(parts, key=load, reverse=True)
    per_part = max(20, time_limit / max(1, len(order)))
    _, _, warnings = prepare(cfg, kw.get("days_count", 5), kw.get("slots_count", 5), kw.get("max_weeks", 15))
    for attempt in range(3):
        done, failed = [], None
        for i, gs in enumerate(order):
            if progress:
                progress(attempt, i, len(order), sorted(gs))
            sub = dict(cfg)
            sub["curriculum"] = [r for r in rows if set(_as_list(r.get("Групи"))) & gs]
            recs, _, err = generate(sub, time_limit=per_part, fixed=done, **kw)
            if err:
                failed = gs
                break
            done += recs
        if failed is None:
            warnings.insert(0, f"Розклад складено частинами ({len(order)}), спроба {attempt + 1}.")
            return done, warnings, None
        order.remove(failed)
        order.insert(0, failed)
    return None, warnings, (f"Не вдалося скласти частину з групами {', '.join(sorted(failed))}. "
                            "Перевір навантаження й обмеження цих груп та їхніх викладачів.")


def generate_auto(cfg, time_limit=120, progress=None, **kw):
    """Спершу вся модель разом; якщо не вийшло — частинами."""
    recs, warnings, err = generate(cfg, time_limit=time_limit, **kw)
    if not err:
        return recs, warnings, None
    return generate_by_parts(cfg, time_limit=time_limit, progress=progress, **kw)


def verify(records, cfg, days_count=5, slots_count=5, max_weeks=15, max_per_day=4, min_per_day=2):
    """Незалежна перевірка готового розкладу. Повертає список проблем."""
    specs, ref, _ = prepare(cfg, days_count, slots_count, max_weeks)
    problems = []
    cnt = defaultdict(int)
    for r in records:
        cnt[tuple(r["groups"]), r["subject"], r["teacher"], r["is_stream"]] += 1
    for s in specs:
        k = (tuple(s["groups"]), s["subject"], s["teacher"], s["is_stream"])
        if cnt.get(k, 0) != s["pairs"]:
            problems.append(f"Години: «{s['subject']}» ({', '.join(s['groups'])}) — {cnt.get(k, 0)} пар замість {s['pairs']}.")
    g_cell, t_cell, r_cell = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in records:
        c = (r["week"], r["day_idx"], r["slot_idx"])
        for g in r["groups"]:
            g_cell[g, *c].append(r)
        if r["teacher"]:
            t_cell[r["teacher"], *c].append(r)
        if not r["online"]:
            r_cell[r["room"], *c].append(r)
        if (r["day_idx"], r["slot_idx"]) in ref["blocked"].get(r["teacher"], set()):
            problems.append(f"Обмеження: {r['teacher']} — тиждень {r['week']}, {r['day']}, {r['slot_idx']} пара.")
        for g in r["groups"]:
            if ref["groups"][g]["practice_day"] == r["day_idx"]:
                problems.append(f"День практики: {g} — тиждень {r['week']}, {r['day']}.")
            if r["week"] - 1 not in ref["groups"][g]["wset"]:
                problems.append(f"Тижні: {g} має заняття в тижні {r['week']}, коли не навчається (практика або поза семестром).")
    first = {}
    for r in records:
        k = (tuple(r["groups"]), r["subject"].lower(), r["teacher"], r["is_stream"])
        first[k] = min(first.get(k, 10 ** 9), r["week"])
    for (gs, subj, t, stream), wk in first.items():
        if stream:
            continue
        lect = [w for (lg, ls, lt, lst), w in first.items() if lst and ls == subj and lt == t and set(lg) & set(gs)]
        if lect and min(lect) > wk:
            problems.append(f"Лекція пізніше практичних: «{subj}» ({', '.join(gs)}) — практичні з тижня {wk}, лекція з тижня {min(lect)}.")
    for name, cells in (("група", g_cell), ("викладач", t_cell), ("аудиторія", r_cell)):
        for (who, w, d, sl), rs in cells.items():
            if len(rs) > 1:
                problems.append(f"Накладка ({name}) {who}: тиждень {w}, {DAY_NAMES[d]}, {sl} пара.")
    for g in ref["groups"]:
        for w in range(1, max_weeks + 1):
            week_total = sum(1 for d in range(days_count) for sl in range(slots_count) if g_cell.get((g, w, d, sl)))
            for d in range(days_count):
                busy = [sl for sl in range(slots_count) if g_cell.get((g, w, d, sl))]
                if busy and busy[-1] - busy[0] + 1 != len(busy):
                    problems.append(f"Вікно: {g} — тиждень {w}, {DAY_NAMES[d]}, пари {busy}.")
                if len(busy) > max_per_day:
                    problems.append(f"Забагато пар: {g} — тиждень {w}, {DAY_NAMES[d]}, {len(busy)} пар.")
                if 0 < len(busy) < min_per_day and week_total >= min_per_day:
                    problems.append(f"Замало пар: {g} — тиждень {w}, {DAY_NAMES[d]}, {len(busy)} пара.")
    return problems


# ======================= ІНТЕРФЕЙС =======================
import io
import json
import re

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Генератор розкладу академії", layout="wide")
st.title("🎓 Система автоматизованого формування розкладу")

# --- КОНСТАНТИ ---
SLOT_DETAILS = [
    {"num": 0, "label": "0 пара", "time": "12:45 - 13:55"},
    {"num": 1, "label": "1 пара", "time": "14:05 - 15:15"},
    {"num": 2, "label": "2 пара", "time": "15:25 - 16:35"},
    {"num": 3, "label": "3 пара", "time": "16:45 - 17:55"},
    {"num": 4, "label": "4 пара", "time": "18:05 - 19:15"},
]
SLOT_LABELS = [f"{s['label']}\n({s['time']})" for s in SLOT_DETAILS]
SLOT_OPTIONS = [f"{s['label']} ({s['time']})" for s in SLOT_DETAILS]

# 1. Параметри
st.markdown("### 1. Параметри сітки та розкладу")
c1, c2, c3 = st.columns(3)
with c1:
    max_weeks = st.number_input("Тижнів у семестрі (найбільше серед груп)", min_value=1, max_value=25, value=15)
with c2:
    days_count = st.number_input("Навчальних днів на тиждень", min_value=1, max_value=6, value=5)
with c3:
    slots_count = st.number_input("Пар на день", min_value=1, max_value=5, value=5)
c4, c5, c6 = st.columns(3)
with c4:
    min_per_day = st.number_input("Мінімум пар на день для групи", min_value=1, max_value=5, value=2,
                                  help="Менше можна лише тоді, коли за весь тиждень у групи менше пар")
    max_per_day = st.number_input("Максимум пар на день для групи", min_value=1, max_value=5, value=min(4, int(slots_count)))
with c5:
    time_limit = st.number_input("Час пошуку, секунд", min_value=10, max_value=1800, value=120, step=10)
with c6:
    lectures_first = st.checkbox("Лекція потоку раніше практичних", value=True)
    stable = st.checkbox("Стабільні місця пар щотижня", value=True,
                         help="Дисципліна стоїть на тих самих місцях кожного тижня. "
                              "Якщо розклад не знаходиться — вимкни, тоді місця можуть змінюватися.")

ACTIVE_DAYS = DAY_NAMES[:days_count]
ACTIVE_SLOTS = SLOT_LABELS[:slots_count]
ACTIVE_SLOT_OPTIONS = SLOT_OPTIONS[:slots_count]

st.info("ℹ️ Кольори: блакитний — ОНЛАЙН, світло-зелений — ПОТІК, рожевий — тижні практики групи")

# --- Стан ---
if "schedule_data" not in st.session_state:
    st.session_state.schedule_data = None
if "cfg_groups" not in st.session_state:
    st.session_state.cfg_groups = pd.DataFrame([{"Група": "ПО-11Б", "Кількість тижнів": 15, "Тижні практики": "", "День практики": "Немає"}])
if "cfg_teachers" not in st.session_state:
    st.session_state.cfg_teachers = "Усатенко В.М."
if "cfg_rooms" not in st.session_state:
    st.session_state.cfg_rooms = "1 авдиторія\n15 авдиторія\n27-А Комп'ютерний клас\nОНЛАЙН"


def normalize_slot_items(items):
    """Підганяє назви пар з файлу (напр. «0 пара (12:42 - ...)») під поточний список."""
    out = []
    for it in items or []:
        s = str(it)
        if "Всі пари" in s:
            out.append("Всі пари")
            continue
        m = re.match(r"\s*(\d+)\s*пара", s)
        if m and int(m.group(1)) < len(SLOT_OPTIONS):
            out.append(SLOT_OPTIONS[int(m.group(1))])
    return out


def handle_json_upload():
    up = st.session_state.get("config_file_uploader")
    if not up:
        return
    try:
        cfg = json.load(up)
        if "groups" in cfg:
            gdf = pd.DataFrame(cfg["groups"])
            if "Тижні практики" not in gdf.columns:
                gdf.insert(min(2, len(gdf.columns)), "Тижні практики", "")
            gdf["Тижні практики"] = gdf["Тижні практики"].fillna("").astype(str)
            st.session_state.cfg_groups = gdf
        if "teachers" in cfg:
            st.session_state.cfg_teachers = cfg["teachers"]
        if "rooms" in cfg:
            st.session_state.cfg_rooms = cfg["rooms"]
        if "limits" in cfg:
            for lim in cfg["limits"]:
                lim["Недоступні пари"] = normalize_slot_items(lim.get("Недоступні пари"))
            st.session_state.cfg_limits = pd.DataFrame(cfg["limits"])
        if "curriculum" in cfg:
            for row in cfg["curriculum"]:
                if not row.get("Аудиторія"):
                    row["Аудиторія"] = AUTO_ROOM
            st.session_state.cfg_curriculum = pd.DataFrame(cfg["curriculum"])
        for k in ("g_ed", "l_ed", "c_ed"):
            st.session_state.pop(k, None)
        st.session_state.schedule_data = None
    except Exception as e:
        st.session_state.upload_error = f"Помилка формату файлу: {e}"


st.markdown("### 💾 Збереження та відновлення даних")
st.file_uploader("📂 Завантажити .json конфігурацію", type=["json"], key="config_file_uploader", on_change=handle_json_upload)
if st.session_state.get("upload_error"):
    st.error(st.session_state.pop("upload_error"))

# 2. Довідники
st.markdown("### 2. Довідники закладу")
cg, ct, cr = st.columns(3)
with cg:
    groups_df = st.data_editor(st.session_state.cfg_groups, num_rows="dynamic", use_container_width=True, key="g_ed",
                               column_config={
        "День практики": st.column_config.SelectboxColumn(options=["Немає"] + ACTIVE_DAYS),
        "Тижні практики": st.column_config.TextColumn(help="Тижні без занять, напр. 6-9 або 6-7, 12"),
        "Кількість тижнів": st.column_config.NumberColumn(help="Останній тиждень семестру для групи (разом із тижнями практики)")})
with ct:
    teachers_text = st.text_area("Список викладачів", value=st.session_state.cfg_teachers, height=150)
with cr:
    rooms_text = st.text_area("Аудиторії", value=st.session_state.cfg_rooms, height=150)

base_teachers = [t.strip() for t in teachers_text.split("\n") if t.strip()]
base_rooms = [r.strip() for r in rooms_text.split("\n") if r.strip()]
active_groups = groups_df["Група"].dropna().astype(str).str.strip().unique().tolist() if not groups_df.empty else []

# 3. Обмеження викладачів
st.markdown("### 3. Обмеження викладачів (сумісники тощо)")
if "cfg_limits" not in st.session_state:
    st.session_state.cfg_limits = pd.DataFrame([{"Викладач": base_teachers[0] if base_teachers else "",
                                                 "День тижня": "Вівторок", "Недоступні пари": ["Всі пари"]}])
limits_df = st.data_editor(st.session_state.cfg_limits, num_rows="dynamic", column_config={
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "День тижня": st.column_config.SelectboxColumn(options=["Всі дні"] + ACTIVE_DAYS),
    "Недоступні пари": st.column_config.MultiselectColumn(options=["Всі пари"] + ACTIVE_SLOT_OPTIONS),
}, use_container_width=True, key="l_ed")

# 4. Навчальний план
st.markdown("### 4. Навчальний план")
if "cfg_curriculum" not in st.session_state:
    st.session_state.cfg_curriculum = pd.DataFrame([{
        "Групи": ["ПО-11Б"], "Предмет": "Педагогіка", "Викладач": base_teachers[0] if base_teachers else "",
        "Годин на семестр": 30, "Формат": "Очно", "Потокова лекція?": "Ні", "Аудиторія": AUTO_ROOM}])
curriculum_df = st.data_editor(st.session_state.cfg_curriculum, num_rows="dynamic", column_config={
    "Групи": st.column_config.MultiselectColumn(options=active_groups),
    "Викладач": st.column_config.SelectboxColumn(options=base_teachers),
    "Формат": st.column_config.SelectboxColumn(options=["Очно", "Онлайн"]),
    "Потокова лекція?": st.column_config.SelectboxColumn(options=["Ні", "Так"]),
    "Аудиторія": st.column_config.SelectboxColumn(options=[AUTO_ROOM] + base_rooms),
}, use_container_width=True, key="c_ed")


def _records(df):
    """DataFrame -> список словників без NaN (списки лишаються списками)."""
    out = []
    for rec in df.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if isinstance(v, float) and pd.isna(v):
                v = None
            elif hasattr(v, "tolist"):
                v = v.tolist()
            clean[k] = v
        out.append(clean)
    return out


config = {"groups": _records(groups_df), "teachers": teachers_text, "rooms": rooms_text,
          "limits": _records(limits_df), "curriculum": _records(curriculum_df)}
st.download_button("📥 Зберегти введені налаштування у .json",
                   data=json.dumps(config, ensure_ascii=False, indent=2),
                   file_name="rozklad_config.json", mime="application/json", use_container_width=True)

# --- ГЕНЕРАЦІЯ ---
st.markdown("---")
params = dict(days_count=int(days_count), slots_count=int(slots_count), max_weeks=int(max_weeks),
              max_per_day=int(max_per_day), min_per_day=int(min_per_day),
              lectures_first=lectures_first, stable=stable)

if st.button("🚀 Згенерувати розклад", type="primary", use_container_width=True):
    with st.status("Складаю розклад…", expanded=True) as box:
        box.write("Пробую скласти весь розклад разом…")

        def progress(attempt, i, n, gs):
            box.write(f"Частина {i + 1} з {n} (спроба {attempt + 1}): {', '.join(gs)}")

        records, warns, err = generate_auto(config, time_limit=int(time_limit), progress=progress, **params)
        if err:
            box.update(label="Розклад не знайдено", state="error")
            st.session_state.schedule_data = None
            st.error(err)
            for w in warns:
                st.warning(w)
        else:
            problems = verify(records, config, int(days_count), int(slots_count), int(max_weeks),
                              int(max_per_day), int(min_per_day))
            st.session_state.schedule_data = {
                "records": records, "warnings": warns, "problems": problems,
                "weeks": int(max_weeks), "groups": active_groups, "teachers": base_teachers,
                "practice": {g["Група"]: sorted(parse_weeks(g.get("Тижні практики"), int(max_weeks)))
                             for g in config["groups"] if g.get("Група")},
                "days": list(ACTIVE_DAYS), "slots": list(ACTIVE_SLOTS),
            }
            box.update(label="Готово!", state="complete")

# --- ПЕРЕГЛЯД ---


def cell_group(r):
    loc = "ОНЛАЙН" if r["online"] else r["room"]
    tag = "\n(ПОТІК)" if r["is_stream"] else ""
    return f"{r['subject']}{tag}\n{r['teacher']}\n{loc}"


def cell_teacher(r):
    loc = "ОНЛАЙН" if r["online"] else r["room"]
    tag = "\n(ПОТІК)" if r["is_stream"] else ""
    return f"{', '.join(r['groups'])}\n{r['subject']}{tag}\n{loc}"


def semester_grid(data, keep, cell, group=None):
    """Рядки — день і пара, стовпці — тижні семестру (тижні практики групи позначено)."""
    pr = set(data.get("practice", {}).get(group, [])) if group else set()
    idx = {}
    for r in data["records"]:
        if keep(r):
            idx[r["day_idx"], r["slot_idx"], r["week"]] = cell(r)
    rows = []
    for d, dn in enumerate(data["days"]):
        for sl, sn in enumerate(data["slots"]):
            row = {"День": dn, "Пара": sn.replace("\n", " ")}
            for w in range(1, data["weeks"] + 1):
                row[f"Т{w} практика" if w in pr else f"Т{w}"] = "ПРАКТИКА" if w in pr else idx.get((d, sl, w), "")
            rows.append(row)
    return pd.DataFrame(rows)


def week_grid(data, week):
    idx = {}
    for r in data["records"]:
        if r["week"] == week:
            for g in r["groups"]:
                idx[g, r["day_idx"], r["slot_idx"]] = cell_group(r)
    rows = []
    for d, dn in enumerate(data["days"]):
        for sl, sn in enumerate(data["slots"]):
            row = {"День": dn, "Пара": sn.replace("\n", " ")}
            for g in data["groups"]:
                row[g] = idx.get((g, d, sl), "")
            rows.append(row)
    return pd.DataFrame(rows)


def style_cell(v):
    if not isinstance(v, str) or not v:
        return ""
    u = v.upper()
    if "ОНЛАЙН" in u:
        return "background-color: #CCFFFF; color: #000; white-space: pre-wrap;"
    if "(ПОТІК)" in u:
        return "background-color: #D5E8D4; color: #000; white-space: pre-wrap;"
    if u == "ПРАКТИКА":
        return "background-color: #FF1493; color: #fff; font-weight: bold;"
    if u in ("ПОНЕДІЛОК", "ВІВТОРОК", "СЕРЕДА", "ЧЕТВЕР", "П'ЯТНИЦЯ", "СУБОТА") or "ПАРА" in u[:7]:
        return ""
    return "background-color: #f5f5f5; color: #000; white-space: pre-wrap;"


if st.session_state.schedule_data:
    data = st.session_state.schedule_data
    if data["problems"]:
        st.error(f"Перевірка знайшла проблем: {len(data['problems'])}")
        with st.expander("Список проблем"):
            st.write("\n".join(f"- {p}" for p in data["problems"]))
    else:
        st.success("✅ Перевірка: усі години розставлено, накладок і вікон немає, обмеження викладачів і дні практики дотримано.")
    with st.expander("Повідомлення"):
        st.write("\n".join(f"- {w}" for w in data["warnings"]))

    view = st.radio("Перегляд:", ["🎓 Група — весь семестр", "👨‍🏫 Викладач — весь семестр", "📅 Тиждень — усі групи"],
                    horizontal=True)
    if view.startswith("🎓"):
        g = st.selectbox("Група:", data["groups"])
        df = semester_grid(data, lambda r: g in r["groups"], cell_group, group=g)
    elif view.startswith("👨"):
        busy = sorted({r["teacher"] for r in data["records"] if r["teacher"]})
        t = st.selectbox("Викладач:", busy)
        df = semester_grid(data, lambda r: r["teacher"] == t, cell_teacher)
    else:
        w = st.selectbox("Тиждень:", range(1, data["weeks"] + 1))
        df = week_grid(data, w)
    st.dataframe(df.style.map(style_cell), use_container_width=True, height=600, hide_index=True)

    # --- EXCEL ---
    def sheet_name(prefix, name, used):
        base = re.sub(r"[\[\]:*?/\\]", "", f"{prefix} {name}")[:31].strip()
        n, s = 2, base
        while s in used:
            s = f"{base[:28]}~{n}"
            n += 1
        used.add(s)
        return s

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book
        base = {"text_wrap": True, "valign": "vcenter", "align": "center", "border": 1, "font_size": 9}
        f_cell = wb.add_format(base)
        f_onl = wb.add_format({**base, "bg_color": "#CCFFFF"})
        f_str = wb.add_format({**base, "bg_color": "#D5E8D4"})
        f_head = wb.add_format({**base, "bold": True, "bg_color": "#D7E4BC"})
        f_prac = wb.add_format({"bg_color": "#FF1493", "font_color": "#FFFFFF", "bold": True, "font_size": 20,
                                "rotation": 90, "align": "center", "valign": "vcenter", "border": 1})
        used = set()

        def put(df, name, title):
            ws = wb.add_worksheet(name)
            writer.sheets[name] = ws
            ws.write(0, 0, title, wb.add_format({"bold": True, "font_size": 12}))
            for c, col in enumerate(df.columns):
                ws.write(1, c, col, f_head)
                ws.set_column(c, c, 12 if c < 2 else 22)
            prac_cols = {c for c, col in enumerate(df.columns) if str(col).endswith("практика")}
            for r_i, row in enumerate(df.itertuples(index=False), start=2):
                ws.set_row(r_i, 48)
                for c, v in enumerate(row):
                    if c in prac_cols:
                        continue
                    v = "" if v is None else str(v)
                    f = f_head if c < 2 else (f_onl if "ОНЛАЙН" in v.upper() else f_str if "(ПОТІК)" in v.upper() else f_cell)
                    ws.write(r_i, c, v, f)
            last = len(df) + 1
            for c in prac_cols:
                # увесь тиждень практики — одна рожева клітинка з написом під кутом 90°
                ws.merge_range(2, c, last, c, "ПРАКТИКА", f_prac) if last > 2 else ws.write(2, c, "ПРАКТИКА", f_prac)
            ws.freeze_panes(2, 2)

        chk = wb.add_worksheet(sheet_name("", "Перевірка", used))
        lines = (["Проблем не знайдено: години, накладки, вікна, обмеження — усе гаразд."]
                 if not data["problems"] else data["problems"]) + [""] + data["warnings"]
        for i, line in enumerate(lines):
            chk.write(i, 0, line)
        chk.set_column(0, 0, 120)

        for g in data["groups"]:
            if any(g in r["groups"] for r in data["records"]):
                put(semester_grid(data, lambda r, g=g: g in r["groups"], cell_group, group=g),
                    sheet_name("Г", g, used), f"Розклад групи {g} на семестр")
        for t in sorted({r["teacher"] for r in data["records"] if r["teacher"]}):
            put(semester_grid(data, lambda r, t=t: r["teacher"] == t, cell_teacher),
                sheet_name("В", t, used), f"Розклад викладача {t} на семестр")
        for w in range(1, data["weeks"] + 1):
            put(week_grid(data, w), sheet_name("Тиждень", str(w), used), f"Тиждень {w} — усі групи")

    st.download_button("📥 Завантажити повний розклад Excel (групи, викладачі, тижні)", data=output.getvalue(),
                       file_name="Rozklad_semestr.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
