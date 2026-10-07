#!/usr/bin/env python3
"""Build league-data.js for the Madden League Stats canvas from a Companion export.

    python3 build_league_data.py [export-folder] [output.js]

With no folder given it uses the export this project sits in or next to, else the
newest madden-export-* folder in ~/Downloads.

The export folder is read dynamically -- nothing about the number of weeks is
hard-coded:

    teams.csv, players.csv
    schedules/<stage>/week-N.csv       one file per week (scores, home/away)
    stats/<stage>/<N>/<Team>/player-stats.csv   one folder per played week

Every numbered folder under stats/<stage>/ becomes a week in the output, plus
any week that only has a schedule file (shown as upcoming). Drop week 3, 4, ...
into the export, re-run, and the canvas picks them up.

If a week has stats but its schedule file is empty (the exporter sometimes
writes only a header row), matchups come from the scheduleId on the stat rows
and scores are rebuilt from the scoring plays, then reconciled against the
season totals in teams.csv.
"""
import csv
import datetime
import glob
import json
import os
import re
import sys
from collections import defaultdict

STAGE = 'reg'
# Headshots are not downloaded: the page loads each one from EA's ratings site by the export's portraitId.
PORTRAIT_URL = 'https://ratings-images-prod.pulse.ea.com/madden-nfl-27/portraits/{id}.png'

POS = {  # export position -> (label, long name, group, side)
    'QB': ('QB', 'Quarterback', 'QB', 'O'), 'HB': ('HB', 'Halfback', 'RB', 'O'), 'FB': ('FB', 'Fullback', 'RB', 'O'),
    'WR': ('WR', 'Wide Receiver', 'WR', 'O'), 'TE': ('TE', 'Tight End', 'TE', 'O'),
    'LT': ('LT', 'Left Tackle', 'OL', 'O'), 'LG': ('LG', 'Left Guard', 'OL', 'O'), 'C': ('C', 'Center', 'OL', 'O'),
    'RG': ('RG', 'Right Guard', 'OL', 'O'), 'RT': ('RT', 'Right Tackle', 'OL', 'O'),
    'LEDG': ('LE', 'Left Edge', 'DL', 'D'), 'REDG': ('RE', 'Right Edge', 'DL', 'D'), 'DT': ('DT', 'Defensive Tackle', 'DL', 'D'),
    'LE': ('LE', 'Left Edge', 'DL', 'D'), 'RE': ('RE', 'Right Edge', 'DL', 'D'),
    'SAM': ('SLB', 'Sam Linebacker', 'LB', 'D'), 'MIKE': ('MLB', 'Mike Linebacker', 'LB', 'D'), 'WILL': ('WLB', 'Will Linebacker', 'LB', 'D'),
    'LOLB': ('SLB', 'Sam Linebacker', 'LB', 'D'), 'MLB': ('MLB', 'Mike Linebacker', 'LB', 'D'), 'ROLB': ('WLB', 'Will Linebacker', 'LB', 'D'),
    'CB': ('CB', 'Cornerback', 'DB', 'D'), 'FS': ('FS', 'Free Safety', 'DB', 'D'), 'SS': ('SS', 'Strong Safety', 'DB', 'D'),
    'K': ('K', 'Kicker', 'ST', 'S'), 'P': ('P', 'Punter', 'ST', 'S'), 'LS': ('LS', 'Long Snapper', 'ST', 'S'),
}
RATINGS = {
    'QB': [('Throw power', 'throwPowerRating'), ('Short accuracy', 'throwAccShortRating'), ('Mid accuracy', 'throwAccMidRating'),
           ('Deep accuracy', 'throwAccDeepRating'), ('Awareness', 'awareRating'), ('Speed', 'speedRating')],
    'RB': [('Speed', 'speedRating'), ('Acceleration', 'accelRating'), ('Agility', 'agilityRating'),
           ('Break tackle', 'breakTackleRating'), ('Carrying', 'carryRating'), ('Juke move', 'jukeMoveRating')],
    'WR': [('Speed', 'speedRating'), ('Catching', 'catchRating'), ('Short routes', 'routeRunShortRating'),
           ('Medium routes', 'routeRunMedRating'), ('Deep routes', 'routeRunDeepRating'), ('Catch in traffic', 'cITRating')],
    'TE': [('Speed', 'speedRating'), ('Catching', 'catchRating'), ('Short routes', 'routeRunShortRating'),
           ('Catch in traffic', 'cITRating'), ('Run block', 'runBlockRating'), ('Strength', 'strengthRating')],
    'OL': [('Pass block', 'passBlockRating'), ('Run block', 'runBlockRating'), ('Strength', 'strengthRating'),
           ('Impact block', 'impactBlockRating'), ('Pass blk power', 'passBlockPowerRating'), ('Awareness', 'awareRating')],
    'DL': [('Power moves', 'powerMovesRating'), ('Finesse moves', 'finesseMovesRating'), ('Block shedding', 'blockShedRating'),
           ('Strength', 'strengthRating'), ('Tackling', 'tackleRating'), ('Speed', 'speedRating')],
    'LB': [('Tackling', 'tackleRating'), ('Pursuit', 'pursuitRating'), ('Play recognition', 'playRecRating'),
           ('Zone coverage', 'zoneCoverRating'), ('Hit power', 'hitPowerRating'), ('Speed', 'speedRating')],
    'DB': [('Speed', 'speedRating'), ('Man coverage', 'manCoverRating'), ('Zone coverage', 'zoneCoverRating'),
           ('Press', 'pressRating'), ('Play recognition', 'playRecRating'), ('Tackling', 'tackleRating')],
    'ST': [('Kick power', 'kickPowerRating'), ('Kick accuracy', 'kickAccRating'), ('Awareness', 'awareRating'),
           ('Strength', 'strengthRating'), ('Speed', 'speedRating'), ('Toughness', 'toughRating')],
}
MAIN_LABEL = {'QB': 'Pass yards', 'RB': 'Rush yards', 'WR': 'Rec yards', 'TE': 'Rec yards', 'DL': 'Tackles',
              'LB': 'Tackles', 'DB': 'Tackles', 'ST': 'FG made', 'OL': 'Games'}
CARD_LABELS = {
    'QB': ['Pass yards', 'Pass TD', 'INT', 'Comp %', 'Rating', 'Rush yards'],
    'RB': ['Rush yards', 'Carries', 'Rush TD', 'Yds / carry', 'Receptions', 'Rec yards'],
    'WR': ['Receptions', 'Rec yards', 'Rec TD', 'Yds / rec', 'Long', 'Drops'],
    'TE': ['Receptions', 'Rec yards', 'Rec TD', 'Yds / rec', 'Long', 'Drops'],
    'OL': ['Games played'],
    'DL': ['Tackles', 'Sacks', 'INT', 'Forced fum', 'Pass def', 'Def TD'],
    'LB': ['Tackles', 'Sacks', 'INT', 'Forced fum', 'Pass def', 'Def TD'],
    'DB': ['Tackles', 'Sacks', 'INT', 'Forced fum', 'Pass def', 'Def TD'],
    'ST': ['FG made', 'FG att', 'Long FG', 'XP made', 'Punts', 'Punt avg'],
}
DEV = {0: 'Normal', 1: 'Star', 2: 'Superstar', 3: 'X-Factor'}
SUM = ['passAtt', 'passComp', 'passYds', 'passTDs', 'passInts', 'passSacks', 'rushAtt', 'rushYds', 'rushTDs', 'rushFum',
       'recCatches', 'recYds', 'recTDs', 'recDrops', 'defTotalTackles', 'defSacks', 'defInts', 'defForcedFum', 'defFumRec',
       'defDeflections', 'defTDs', 'defSafeties', 'defIntReturnYds', 'fGMade', 'fGAtt', 'xPMade', 'xPAtt', 'puntAtt', 'puntYds']
MAX = ['passLongest', 'rushLongest', 'recLongest', 'fGLongest', 'puntLongest']


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(f) if f == int(f) else f


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def hexcol(v):
    return '#%06x' % (int(num(v)) & 0xFFFFFF)


def on_color(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return '#111111' if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else '#ffffff'


def fmt_int(n):
    return '{:,}'.format(int(round(n)))


def f1(x):
    return '%.1f' % x


def trim(x):  # 2.0 -> "2", 2.5 -> "2.5"
    return ('%.1f' % x).rstrip('0').rstrip('.')


def passer_rating(c, a, y, td, i):
    if not a:
        return 0.0
    cl = lambda v: max(0.0, min(2.375, v))
    return (cl((c / a - .3) * 5) + cl((y / a - 3) * .25) + cl(td / a * 20) + cl(2.375 - i / a * 25)) / 6 * 100


# ---------------------------------------------------------------- discovery

def numbered(paths, rx):
    out = {}
    for p in paths:
        m = re.search(rx, os.path.basename(p))
        if m:
            out[int(m.group(1))] = p
    return out


def load_schedule(path):
    """Schedule files hold one row of JSON blobs (one per game). Empty -> []."""
    games = []
    with open(path, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.reader(fh))
    for row in rows[1:]:
        for cell in row:
            cell = cell.strip()
            if cell.startswith('{'):
                try:
                    games.append(json.loads(cell))
                except ValueError:
                    pass
    return games


def load_stats(folder):
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, '*', 'player-stats.csv'))):
        rows += read_csv(f)
    return rows


# ---------------------------------------------------------------- build

def build(root):
    teams_raw = read_csv(os.path.join(root, 'teams.csv'))
    players_raw = read_csv(os.path.join(root, 'players.csv'))
    T = {t['teamId']: t for t in teams_raw}

    stat_dirs = numbered([d for d in glob.glob(os.path.join(root, 'stats', STAGE, '*')) if os.path.isdir(d)], r'^(\d+)$')
    sched_files = numbered(glob.glob(os.path.join(root, 'schedules', STAGE, 'week-*.csv')), r'^week-(\d+)\.csv$')
    stats = {w: load_stats(d) for w, d in stat_dirs.items()}
    stats = {w: r for w, r in stats.items() if r}
    scheds = {w: load_schedule(f) for w, f in sched_files.items()}
    scheds = {w: g for w, g in scheds.items() if g}
    weeks = sorted(set(stats) | set(scheds))
    notes = []

    # ---- players
    players = {}
    for p in players_raw:
        tid = p['teamId']
        if tid not in T or p.get('isFreeAgent') == 'true':
            continue
        label, long_name, grp, side = POS.get(p['position'], (p['position'], p['position'], 'ST', 'S'))
        inj = int(num(p['injuryLength']))
        status = 'IR' if p['isOnIR'] == 'true' else ('Healthy' if inj <= 0 else 'Out %d wk%s' % (inj, '' if inj == 1 else 's'))
        h = int(num(p['height']))
        sal = num(p['contractSalary'])
        players[p['rosterId']] = {
            'id': p['rosterId'], 'tid': tid, 'name': (p['firstName'] + ' ' + p['lastName']).strip(),
            'pos': label, 'posName': long_name, 'grp': grp, 'side': side, 'num': str(p['jerseyNum']),
            'ovr': int(num(p['playerBestOvr'])), 'age': int(num(p['age'])), 'ht': '%d\'%d"' % (h // 12, h % 12),
            'wt': int(num(p['weight'])), 'exp': int(num(p['yearsPro'])), 'dev': DEV.get(int(num(p['devTrait'])), 'Normal'),
            'status': status, 'college': p['college'], 'ps': p['isOnPracticeSquad'] == 'true',
            'contract': (('$%.1fM' % (sal / 1e6)) if sal >= 1e6 else '$%dK' % round(sal / 1e3)) if sal else '—', 'len': int(num(p['contractLength'])),
            'yrsLeft': int(num(p['contractYearsLeft'])),
            'pid': str(int(num(p.get('portraitId')))) if num(p.get('portraitId')) else '',
            'ratings': [{'k': k, 'v': int(num(p[c]))} for k, c in RATINGS[grp]],
        }

    # ---- teams
    teams = {}
    for t in teams_raw:
        tid = t['teamId']
        col = hexcol(t['primaryColor'])
        roster = sorted((p for p in players.values() if p['tid'] == tid), key=lambda p: (-p['ovr'], p['name']))
        teams[tid] = {
            'id': tid, 'abbr': t['abbrName'], 'name': t['displayName'], 'city': t['cityName'],
            'full': t['cityName'] + ' ' + t['displayName'], 'color': col, 'on': on_color(col),
            'color2': hexcol(t['secondaryColor']), 'user': t.get('userName', ''), 'ovr': int(num(t['ovrRating'])),
            'div': t['divName'], 'conf': t['conferenceName'], 'injuries': int(num(t['injuryCount'])),
            'roster': [p['id'] for p in roster],
        }
    ab = lambda tid: teams[tid]['abbr']
    users = [t for t in teams.values() if t['user']]
    default_team = (users[0] if users else next(iter(teams.values())))['id']

    # ---- games per week
    def derived_points(rows):
        pts = defaultdict(int)
        for r in rows:
            pts[r['teamId']] += int(6 * (num(r.get('rushTDs')) + num(r.get('recTDs')) + num(r.get('defTDs')))
                                    + 3 * num(r.get('fGMade')) + num(r.get('xPMade')) + 2 * num(r.get('defSafeties')))
        return pts

    games = {}
    for w in weeks:
        gl = []
        if w in scheds:
            for g in scheds[w]:
                a, h = str(g['awayTeamId']), str(g['homeTeamId'])
                if a not in teams or h not in teams:
                    continue
                final = int(g.get('status', 1)) >= 2
                gl.append({'a': a, 'h': h, 'as': int(g['awayScore']) if final else '', 'hs': int(g['homeScore']) if final else '',
                           'final': final, 'gotw': bool(g.get('isGameOfTheWeek')), 'sid': str(g.get('scheduleId', ''))})
        else:
            # no schedule rows: pair teams by the scheduleId on their stat rows
            by_sid = defaultdict(list)
            for r in stats[w]:
                if r['teamId'] in teams and r['teamId'] not in by_sid[r['scheduleId']]:
                    by_sid[r['scheduleId']].append(r['teamId'])
            pts = derived_points(stats[w])
            for sid in sorted(by_sid):
                pair = by_sid[sid]
                if len(pair) != 2:
                    continue
                a, h = sorted(pair, key=ab)
                gl.append({'a': a, 'h': h, 'as': pts[a], 'hs': pts[h], 'final': True, 'gotw': False, 'sid': sid, 'est': True})
            notes.append('Week %d: schedule file has no games; matchups and scores rebuilt from player stats.' % w)
        games[w] = gl

    # ---- repair rebuilt games with the season totals in teams.csv
    est_games = defaultdict(list)
    for w in weeks:
        for g in games[w]:
            if g.get('est'):
                est_games[g['a']].append(g)
                est_games[g['h']].append(g)

    def known(tid):
        pf = pa = home = away = 0
        for w in weeks:
            for g in games[w]:
                if g.get('est') or not g['final'] or tid not in (g['a'], g['h']):
                    continue
                is_home = g['h'] == tid
                pf += g['hs'] if is_home else g['as']
                pa += g['as'] if is_home else g['hs']
                home += is_home
                away += not is_home
        return pf, pa, home, away

    def csv_fits(tid, pf, pa):
        t = T[tid]
        gp = int(num(t['totalWins']) + num(t['totalLosses']) + num(t['totalTies']))
        if not gp:
            return False
        return (abs(pf / gp - num(t['ptsFor'])) <= 0.5 and abs(pa / gp - num(t['ptsAgainst'])) <= 0.5
                and pf - pa == num(t['netPts']))

    for w in weeks:
        for g in games[w]:
            if not g.get('est'):
                continue
            a, h = g['a'], g['h']
            if len(est_games[a]) != 1 or len(est_games[h]) != 1:
                continue  # more than one unknown game per team: keep the stat-derived score
            kpa, kaa, khome_a, kaway_a = known(a)
            kph, kah, khome_h, kaway_h = known(h)
            # home / away from the home+away game counts in teams.csv
            a_home_total = int(num(T[a]['homeWins']) + num(T[a]['homeLosses']) + num(T[a]['homeTies']))
            h_home_total = int(num(T[h]['homeWins']) + num(T[h]['homeLosses']) + num(T[h]['homeTies']))
            if a_home_total - khome_a == 1 and h_home_total - khome_h == 0:
                g['a'], g['h'], g['as'], g['hs'] = h, a, g['hs'], g['as']
                a, h = g['a'], g['h']
                kpa, kaa, kph, kah = kph, kah, kpa, kaa
            # scoring plays miss 2-pt conversions and return TDs: search upward for totals teams.csv agrees with
            best = None
            for xa in range(0, 17):
                for xh in range(0, 17):
                    sa, sh = g['as'] + xa, g['hs'] + xh
                    if csv_fits(a, kpa + sa, kaa + sh) and csv_fits(h, kph + sh, kah + sa):
                        if best is None or xa + xh < best[0]:
                            best = (xa + xh, sa, sh)
            if best:
                g['as'], g['hs'] = best[1], best[2]
                del g['est']
    for w in weeks:
        left = sum(1 for g in games[w] if g.get('est'))
        if left:
            notes.append('Week %d: %d score(s) are estimates (could not be confirmed against teams.csv).' % (w, left))

    # ---- stat accumulation
    def blank():
        d = {k: 0 for k in SUM + MAX}
        d['gp'] = 0
        return d

    def add(acc, r):
        for k in SUM:
            acc[k] += num(r.get(k))
        for k in MAX:
            acc[k] = max(acc[k], num(r.get(k)))
        acc['gp'] += 1

    def card(grp, s):
        cmp_pct = f1(s['passComp'] / s['passAtt'] * 100) if s['passAtt'] else 0
        if grp == 'QB':
            return [fmt_int(s['passYds']), s['passTDs'], s['passInts'], cmp_pct,
                    f1(passer_rating(s['passComp'], s['passAtt'], s['passYds'], s['passTDs'], s['passInts'])) if s['passAtt'] else 0,
                    fmt_int(s['rushYds'])]
        if grp == 'RB':
            return [fmt_int(s['rushYds']), s['rushAtt'], s['rushTDs'], f1(s['rushYds'] / s['rushAtt']) if s['rushAtt'] else 0,
                    s['recCatches'], fmt_int(s['recYds'])]
        if grp in ('WR', 'TE'):
            return [s['recCatches'], fmt_int(s['recYds']), s['recTDs'], f1(s['recYds'] / s['recCatches']) if s['recCatches'] else 0,
                    s['recLongest'], s['recDrops']]
        if grp == 'OL':
            return [s['gp']]
        if grp == 'ST':
            return [s['fGMade'], s['fGAtt'], s['fGLongest'], s['xPMade'], s['puntAtt'],
                    f1(s['puntYds'] / s['puntAtt']) if s['puntAtt'] else '—']
        return [s['defTotalTackles'], trim(s['defSacks']), s['defInts'], s['defForcedFum'], s['defDeflections'], s['defTDs']]

    def line(grp, pos, s):
        gp = '%d GP' % s['gp']
        if grp == 'QB':
            return '%s YDS · %d TD · %d INT' % (fmt_int(s['passYds']), s['passTDs'], s['passInts']) if s['passAtt'] else gp
        if grp == 'RB':
            if s['rushAtt']:
                return '%s YDS · %s AVG · %d TD' % (fmt_int(s['rushYds']), f1(s['rushYds'] / s['rushAtt']), s['rushTDs'])
            if s['recCatches']:
                return '%d REC · %s YDS · %d TD' % (s['recCatches'], fmt_int(s['recYds']), s['recTDs'])
            return gp
        if grp in ('WR', 'TE'):
            return '%d REC · %s YDS · %d TD' % (s['recCatches'], fmt_int(s['recYds']), s['recTDs']) if s['recCatches'] else gp
        if grp == 'ST':
            if s['puntAtt']:
                return '%d PUNTS · %s AVG' % (s['puntAtt'], f1(s['puntYds'] / s['puntAtt']))
            if s['fGAtt'] or s['xPAtt']:
                return '%d/%d FG · %d/%d XP' % (s['fGMade'], s['fGAtt'], s['xPMade'], s['xPAtt'])
            return gp
        if grp == 'OL':
            return gp
        parts = []
        if s['defTotalTackles']:
            parts.append('%d TKL' % s['defTotalTackles'])
        if s['defSacks']:
            parts.append('%s SCK' % trim(s['defSacks']))
        if s['defInts']:
            parts.append('%d INT' % s['defInts'])
        if s['defForcedFum']:
            parts.append('%d FF' % s['defForcedFum'])
        if s['defDeflections']:
            parts.append('%d PD' % s['defDeflections'])
        return ' · '.join(parts) if parts else gp

    def main_val(grp, s):
        return {'QB': s['passYds'], 'RB': s['rushYds'], 'WR': s['recYds'], 'TE': s['recYds'], 'ST': s['fGMade'],
                'OL': s['gp']}.get(grp, s['defTotalTackles'])

    def leaders(acc, tid_of, name_of):
        def base(rid):
            tid = tid_of.get(rid, '')
            return {'rid': rid, 'name': name_of.get(rid, rid), 'tm': ab(tid) if tid in teams else '', 'tid': tid,
                    'pos': players[rid]['pos'] if rid in players else ''}

        def top(key, flt, mk, n=10):
            ids = [r for r in acc if flt(acc[r])]
            ids.sort(key=lambda r: key(acc[r]), reverse=True)
            return [dict(base(r), **mk(acc[r])) for r in ids[:n]]

        return {
            'pass': top(lambda s: (s['passYds'], s['passTDs']), lambda s: s['passAtt'] > 0, lambda s: {
                'ca': '%d/%d' % (s['passComp'], s['passAtt']), 'yds': fmt_int(s['passYds']), 'td': s['passTDs'], 'int': s['passInts'],
                'rtg': f1(passer_rating(s['passComp'], s['passAtt'], s['passYds'], s['passTDs'], s['passInts']))}),
            'rush': top(lambda s: (s['rushYds'], s['rushTDs']), lambda s: s['rushAtt'] > 0, lambda s: {
                'att': s['rushAtt'], 'yds': fmt_int(s['rushYds']), 'avg': f1(s['rushYds'] / s['rushAtt']), 'td': s['rushTDs'],
                'lng': s['rushLongest']}),
            'rec': top(lambda s: (s['recYds'], s['recTDs']), lambda s: s['recCatches'] > 0, lambda s: {
                'rec': s['recCatches'], 'yds': fmt_int(s['recYds']), 'avg': f1(s['recYds'] / s['recCatches']), 'td': s['recTDs'],
                'lng': s['recLongest']}),
            'def': top(lambda s: (s['defSacks'], s['defTotalTackles'], s['defInts']),
                       lambda s: s['defTotalTackles'] > 0 or s['defSacks'] > 0 or s['defInts'] > 0, lambda s: {
                'tk': s['defTotalTackles'], 'sk': trim(s['defSacks']), 'int': s['defInts']}),
            'int': top(lambda s: (s['defInts'], s['defTDs'], s['defDeflections'], s['defTotalTackles']), lambda s: s['defInts'] > 0, lambda s: {
                'int': s['defInts'], 'pd': s['defDeflections'], 'tk': s['defTotalTackles'], 'td': s['defTDs'],
                'yds': fmt_int(s['defIntReturnYds'])}),
            'sack': top(lambda s: (s['defSacks'], s['defForcedFum'], s['defTotalTackles']), lambda s: s['defSacks'] > 0, lambda s: {
                'sk': trim(s['defSacks']), 'tk': s['defTotalTackles'], 'ff': s['defForcedFum'], 'int': s['defInts']}),
            'tkl': top(lambda s: (s['defTotalTackles'], s['defSacks'], s['defInts']), lambda s: s['defTotalTackles'] > 0, lambda s: {
                'tk': s['defTotalTackles'], 'sk': trim(s['defSacks']), 'int': s['defInts'], 'ff': s['defForcedFum']}),
        }

    # ---- award races (unofficial: a production score, there is no award data in the export)
    def off_score(s):
        return (s['passYds'] * .04 + s['passTDs'] * 4 - s['passInts'] * 2 + s['rushYds'] * .1 + s['rushTDs'] * 6
                + s['recCatches'] * .5 + s['recYds'] * .1 + s['recTDs'] * 6 - s['rushFum'] * 2)

    def def_score(s):
        return (s['defTotalTackles'] + s['defSacks'] * 4 + s['defInts'] * 6 + s['defForcedFum'] * 3 + s['defFumRec'] * 2
                + s['defDeflections'] * 1.5 + s['defTDs'] * 6 + s['defSafeties'] * 2)

    def awards(acc, tid_of, stand):
        rows = []
        for rid, s in acc.items():
            if rid not in players:
                continue
            p = players[rid]
            tid = tid_of.get(rid, p['tid'])
            rows.append({'p': p, 'tid': tid, 'o': off_score(s), 'd': def_score(s), 'w': stand.get(tid, {}).get('w', 0),
                         'line': line(p['grp'], p['pos'], s)})

        def top(flt, key, n=5):
            pick = sorted((r for r in rows if flt(r) and key(r) > 0), key=key, reverse=True)[:n]
            return [{'rid': r['p']['id'], 'name': r['p']['name'], 'pos': r['p']['pos'], 'tid': r['tid'],
                     'tm': ab(r['tid']) if r['tid'] in teams else '', 'line': r['line'], 'score': f1(key(r))} for r in pick]

        O = lambda r: r['p']['side'] == 'O'
        Dd = lambda r: r['p']['side'] == 'D'
        rook = lambda r: r['p']['exp'] == 0
        return {
            'mvp': top(lambda r: True, lambda r: max(r['o'] * (1.25 if r['p']['pos'] == 'QB' else 1), r['d']) + 3 * r['w']),  # QB-weighted production + 3 per team win
            'opoy': top(lambda r: O(r) and r['p']['pos'] != 'QB', lambda r: r['o']),     # non-QB offense
            'dpoy': top(Dd, lambda r: r['d']),
            'oroy': top(lambda r: O(r) and rook(r), lambda r: r['o']),
            'droy': top(lambda r: Dd(r) and rook(r), lambda r: r['d']),
        }

    # ---- walk the weeks
    by_week = {}
    season = defaultdict(blank)
    tid_of, name_of = {}, {}
    rec = {tid: {'w': 0, 'l': 0, 't': 0, 'pf': 0, 'pa': 0, 'gp': 0, 'res': []} for tid in teams}
    current = None
    for w in weeks:
        week_acc = defaultdict(blank)
        for r in stats.get(w, []):
            rid = r['rosterId']
            add(week_acc[rid], r)
            add(season[rid], r)
            tid_of[rid] = r['teamId']
            name_of[rid] = players[rid]['name'] if rid in players else r.get('fullName', rid)

        for g in games[w]:
            if not g['final']:
                continue
            for tid, us, them in ((g['a'], g['as'], g['hs']), (g['h'], g['hs'], g['as'])):
                R = rec[tid]
                R['pf'] += us
                R['pa'] += them
                R['gp'] += 1
                res = 'W' if us > them else ('L' if us < them else 'T')
                R[res.lower()] += 1
                R['res'].append(res)
        if any(g['final'] for g in games[w]):
            current = w

        stand = {}
        for tid, R in rec.items():
            streak = ''
            if R['res']:
                n = 1
                while n < len(R['res']) and R['res'][-n - 1] == R['res'][-1]:
                    n += 1
                streak = R['res'][-1] + str(n)
            gp = R['gp']
            stand[tid] = {'rec': '%d-%d' % (R['w'], R['l']) + ('-%d' % R['t'] if R['t'] else ''), 'w': R['w'], 'l': R['l'],
                          't': R['t'], 'pf': R['pf'], 'pa': R['pa'], 'gp': gp, 'ppg': num(round(R['pf'] / gp, 1)) if gp else 0,
                          'papg': num(round(R['pa'] / gp, 1)) if gp else 0, 'diff': R['pf'] - R['pa'], 'streak': streak}
        played = [t for t in teams if stand[t]['gp']]
        off = sorted(played, key=lambda t: (-stand[t]['ppg'], stand[t]['papg'], ab(t)))
        deff = sorted(played, key=lambda t: (stand[t]['papg'], -stand[t]['ppg'], ab(t)))
        dif = sorted(played, key=lambda t: (-stand[t]['diff'], -stand[t]['ppg'], ab(t)))
        for i, t in enumerate(off):
            stand[t]['offRk'] = i + 1
        for i, t in enumerate(deff):
            stand[t]['defRk'] = i + 1
        for i, t in enumerate(dif):
            stand[t]['diffRk'] = i + 1

        out_games = []
        for g in games[w]:
            o = {'a': g['a'], 'h': g['h'], 'as': g['as'], 'hs': g['hs'], 'final': g['final'], 'gotw': g['gotw'],
                 'aAb': ab(g['a']), 'hAb': ab(g['h']), 'aRec': stand[g['a']]['rec'], 'hRec': stand[g['h']]['rec'],
                 'st': ('FINAL · EST' if g.get('est') else 'FINAL') if g['final'] else 'UPCOMING'}
            if g.get('est'):
                o['est'] = True
            out_games.append(o)

        fin = [g for g in out_games if g['final']]

        def label(g):
            win, lose = (('a', 'h') if g['as'] >= g['hs'] else ('h', 'a'))
            return '%s %d–%d %s' % (g[win + 'Ab'], g[win + 's'], g[lose + 's'], g[lose + 'Ab'])

        total = sum(g['as'] + g['hs'] for g in fin)
        kpis = {'total': total, 'avg': num(round(total / len(fin), 1)) if fin else 0, 'games': len(fin),
                'high': label(max(fin, key=lambda g: g['as'] + g['hs'])) if fin else '—',
                'close': label(min(fin, key=lambda g: abs(g['as'] - g['hs']))) if fin else '—',
                'blowout': label(max(fin, key=lambda g: abs(g['as'] - g['hs']))) if fin else '—'}

        grp_of = lambda rid: players[rid]['grp'] if rid in players else 'ST'
        pos_of = lambda rid: players[rid]['pos'] if rid in players else ''
        ids = sorted(r for r in season if r in players)
        by_week[str(w)] = {
            'week': w, 'games': out_games, 'stand': stand, 'off': off, 'def': deff, 'kpis': kpis,
            'leaders': {'season': leaders(season, tid_of, name_of), 'week': leaders(week_acc, tid_of, name_of)},
            'awards': awards(season, tid_of, stand),
            'lines': {r: line(grp_of(r), pos_of(r), season[r]) for r in ids},      # season to date
            'cards': {r: card(grp_of(r), season[r]) for r in ids},                 # season to date
            'mains': {r: main_val(grp_of(r), week_acc[r]) for r in sorted(week_acc) if r in players},  # that week only
        }

    return {
        'generated': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M'),
        'source': os.path.basename(os.path.abspath(root)),
        'portraitUrl': PORTRAIT_URL,
        'weeks': weeks, 'currentWeek': current, 'notes': notes, 'defaultTeam': default_team,
        'teams': teams, 'players': players, 'mainLabel': MAIN_LABEL, 'cardLabels': CARD_LABELS, 'byWeek': by_week,
    }


def find_export(start=None):
    """Newest folder that looks like a Companion export (has teams.csv + stats/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    is_export = lambda d: os.path.isfile(os.path.join(d, 'teams.csv')) and os.path.isdir(os.path.join(d, 'stats'))
    if start:
        return start if is_export(start) else None
    # downloads made by fetch_export.py win: newest unzipped export under exports/
    fetched = [d for d in glob.glob(os.path.join(here, 'exports', '*')) + glob.glob(os.path.join(here, 'exports', '*', '*')) if is_export(d)]
    if fetched:
        return max(fetched, key=lambda d: os.path.getmtime(os.path.join(d, 'teams.csv')))
    for d in (os.getcwd(), here, os.path.dirname(here)):
        if is_export(d):
            return d
    found = []
    for base in (os.getcwd(), here, os.path.dirname(here), os.path.expanduser('~/Downloads')):
        found += [d for d in glob.glob(os.path.join(base, 'madden-export-*')) if is_export(d)]
    return max(found, key=os.path.basename) if found else None


def to_js(data):
    return 'window.LEAGUE_DATA = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'


def main():
    root = find_export(sys.argv[1] if len(sys.argv) > 1 else None)
    if not root:
        sys.exit(__doc__ + '\nNo export folder found (needs teams.csv and a stats/ folder).')
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'league-data.js')
    data = build(root)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(to_js(data))
    print('export: %s' % root)
    print('weeks found: %s  (current: %s)' % (data['weeks'], data['currentWeek']))
    for w in data['weeks']:
        k = data['byWeek'][str(w)]['kpis']
        print('  week %d: %d games final, %d pts, high %s' % (w, k['games'], k['total'], k['high']))
    for n in data['notes']:
        print('  note: ' + n)
    print('wrote %s (%d KB)' % (out, os.path.getsize(out) // 1024))


if __name__ == '__main__':
    main()
