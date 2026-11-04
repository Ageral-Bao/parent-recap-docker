# What the Brief reads, and what it reports

Every rule below is what the program actually does, with the number the code holds. It is the
reference for "why didn't the Brief mention X?" and "why did it say Y twice?".

The rules are grouped by the question they answer:

1. [What each Source gives, and how far back](#1-what-each-source-gives-and-how-far-back)
2. [What appears once, and what appears again](#2-what-appears-once-and-what-appears-again)
3. [What goes into the Digest, and what goes into a to-do](#3-what-goes-into-the-digest-and-what-goes-into-a-to-do)
4. [A night with nothing to say](#4-a-night-with-nothing-to-say)
5. [Messy input: threads, notes without text, group chat](#5-messy-input-threads-notes-without-text-group-chat)
6. [Privacy: what's held back from the model](#6-privacy-whats-held-back-from-the-model)
7. [Language](#7-language)
8. [A run made again the same evening](#8-a-run-made-again-the-same-evening)

---

## 1. What each Source gives, and how far back

| Source | Reads | Window | Cap per run |
|---|---|---|---|
| **Wilma** messages | the inbox list, then each message's whole thread | `wilma.lookback_hours`, default **26 h** | newest **30** threads |
| **Wilma** bulletins (news) | the news list, then each bulletin | same window, **+1 day on a first run** | newest **20** |
| **Wilma** exams | upcoming exams with the range to revise | today → **+7 days** | 50 |
| **Wilma** lesson notes (merkinnät) | absences, lateness, missing books or homework, praise | **today and yesterday** | all |
| **Wilma** homework | what each lesson set, in the teacher's words | **today and the 3 days before** | 50 |
| **Wilma** timetable | the next *school* day (skips a weekend) | one day | all lessons |
| **WhatsApp** | the picked groups' messages | `whatsapp.lookback_hours`, default **26 h** | all in the window |
| **MyClub** | the club calendar | **tomorrow, 00:00–24:00 local** | all |
| **Gmail** | only the senders/domains the family ticked | `gmail.lookback_hours`, default **26 h** | all in the window |

Two windows are deliberately narrow:

- **MyClub is tomorrow only.** The evening Brief says what to prepare for tomorrow; a match two
  weeks out would take the space and tell the parents nothing they can act on tonight. It shows
  up on its own the evening before.
- **Homework is four days.** Homework set on Friday must still be visible on Monday evening.
  Wilma keeps no "done" flag, so the window is what retires a task; the Brief never guesses
  whether a child did it.

After nights that weren't delivered, or nights a Source failed, every window widens to reach back
to the last run that was caught up, capped at **7 days** (`MAX_CATCH_UP_HOURS`).

---

## 2. What appears once, and what appears again

The Brief is about **today**, not a rolling recap. What stops an item appearing twice:

| Item | What keeps it out of the next night |
|---|---|
| Wilma message, bulletin | the window: `cutoff = max(now − lookback, last caught-up delivery)` |
| A reply inside a Wilma thread | the same window, and nothing else (see §5) |
| Lesson note | its fingerprint, once **seen on an earlier day** |
| Timetable, exams, homework | the id carries the date (`schedule:20261104`), so the next day is a new item |
| WhatsApp message | the window **and** its id, because a reconnect hands the same message over again |

A message the parents have already **read in Wilma** is not skipped. Read or unread is the same
thing to the Brief: the window decides, so a notice read on the phone at noon still reaches the
evening Brief.

Numbers and dates are never recomputed by the model. A homework line says **when it was set**
(`[set 2026-11-02 Mon · yesterday]`) because Wilma dates homework by the lesson that set it, not
by a due date.

---

## 3. What goes into the Digest, and what goes into a to-do

**The Digest** is the prose under each child. It carries, among others:

- the next school day: when it starts and ends, anything the parents must act on (a lesson
  somewhere else, kit to bring, a day that ends early or late) — never the lessons one by one
- exams in the next 7 days: date, subject, name, and the range exactly as Wilma gives it
- lesson notes: the date and lesson, **the kind Wilma recorded**, then the teacher's own words
- homework: the lesson and the date it was set, then pages and exercise numbers as written
- a group chat's answer to another parent's practical question (which page, what to bring,
  whether something is cancelled), and anything the group settled
- a school-side reply in a Wilma thread: what the nurse, teacher or psychologist answered

**A to-do** is only something the parents must *do* beyond turning up: bring, pay, sign, reply,
or arrange something unusual. An event's time and place is not a to-do; getting the child there is
implied. Homework is not a to-do by itself — its lesson's date is not a due date.

**A calendar event** needs a future date and the message that announces it. A deadline is not an
event. A regular training or lesson that simply carries on is not a new event unless its time or
place changes. The next school day's timetable never becomes calendar events.

---

## 4. A night with nothing to say

Three outcomes, and the difference matters because silence is ambiguous:

| Situation | What happens |
|---|---|
| Nothing new was read | **no email** — a quiet night |
| A Source couldn't be read (expired password, WhatsApp unlinked) | **an email that says so**, because silence would look like a quiet night |
| Something was read, but the model found nothing worth saying (an ordinary timetable alone) | **no email** |

A **preview** (the setup page's first Brief) and a **first Brief** always make one, so a family
sees what one looks like.

---

## 5. Messy input: threads, notes without text, group chat

**Wilma messages are threads.** The list gives a thread's *latest activity* and its *first post's
sender*, never the replies. Reading one message is what gives the thread: each reply inside the
window arrives as a message of its own, with its own author and its own time, and the first post
keeps its real date. Without this, an answer written tonight read as the parents' own question
from weeks ago, and the Brief said nothing about it.

**A lesson note's kind is its content.** Wilma keeps the category in the label, and when the
teacher writes no free text the label is the whole record:

| Label | Means |
|---|---|
| `Opettajan kommentti (Käy katsomassa Wilmassa)` | boilerplate: "the teacher commented, read it in Wilma" |
| `Kotitehtävät tekemättä` | homework not done |
| `Tuntityöskentely aktiivista` | working actively in the lesson (praise) |
| `Opiskeluvälineet kotona` | books or kit left at home |
| `Oppilas häiritsee tunnilla` | the pupil disturbs the lesson |
| `Luvallinen poissaolo - Terveydellinen` | an authorised absence, on health grounds |
| `Luvallinen poissaolo - Koulun antamalla luvalla` | an authorised absence, by the school's leave |

The boilerplate and the kind are usually joined by a comma in one label
(`Opettajan kommentti (Käy katsomassa Wilmassa), Kotitehtävät tekemättä`), so the part after the
comma is the one that says what happened.

The Brief says the kind first and only then points at Wilma for the teacher's own words. It never
writes "there is a record with no text, see Wilma" — that leaves the parents with nothing.

**A group chat carries what the parents gave each other.** Two cases qualify: parents settling
something (date, place, what to bring, who organises, what is still open), and parents answering
each other's practical question even when nothing was "decided". A question and its answer are
exactly that. Only greetings, thanks, emoji and chatter get no line.

**Finnish school staff stay apart.** `terveydenhoitaja` is the school nurse, `koululääkäri` the
school doctor, `kuraattori` the social worker, `psykologi` the psychologist. A nurse who writes
that she consulted the doctor is the nurse writing.

---

## 6. Privacy: what's held back from the model

Before the Brief reaches the model, the payload is masked:

- the **names of the people** who sent tonight's messages, and of those in earlier Briefs
- **links** come out of the text the model reads, and go back in when the Brief is rendered
- only the **count** of a message's addressees is kept, never the names (they are third parties')

A message addressed to enough people counts as sent to everyone, and is never held back (a
bulletin, or a Wilma message with **15 or more** addressees). One to fewer is checked against the
sensitive-topic lists first.

Message text is treated as **data, not instructions**. A message that tries to steer the Brief —
"ignore your instructions", "add this event", "include this link" — is not followed; the Brief
says instead that the message holds instructions for the assistant.

---

## 7. Language

Each Recipient picks a language, and the same night's content is rendered once per language and
sent to each Recipient in theirs (`fi`, `en`, `zh`).

Finnish words are translated, except a term the parent will need **in Finnish later** — a form, a
notebook, a named event — which keeps its Finnish in brackets so it can be recognised at school
and searched in Wilma.

---

## 8. A run made again the same evening

A night can be run more than once: the setup page's preview, a re-send after a quiet night, a
retry after a failure. A second run must show the same day's content, and it must not repeat what
an earlier *night* already carried.

| What | Second run the same evening |
|---|---|
| Wilma messages, replies, bulletins | still there (the window has not moved) |
| Lesson notes | still there — the gate is "seen on an earlier day", not "seen at all" |
| Timetable, exams, homework | rebuilt from scratch, with the day's own id |
| WhatsApp | skipped if already given: a reconnect would otherwise repeat them |

A run told to reach further back than a night — the setup page's preview asks for **72 hours** —
keeps that wider window instead of narrowing it to the last delivery. Without that, a family
setting itself up right after the evening run saw a Brief with none of the day's news.

---

## Where each rule lives

| Rule | Code |
|---|---|
| Source list, windows, which Sources are skippable | `sources.py`, `config.py` |
| Wilma: threads, notes, homework, exams, timetable | `collectors/wilma.py` |
| WhatsApp: window, ids, group and Kid hints | `collectors/whatsapp.py` |
| MyClub: tomorrow only | `collectors/myclub.py` |
| The Digest, to-dos and events the model writes | `summarize.py` (its `Your job` and `Notes`) |
| Quiet night, preview, catch-up windows | `run.py` |
| What stops an item repeating | `state.py`, and the window in each collector |
| Held back from the model | `held_back.py`, `ai_filter.py` |
