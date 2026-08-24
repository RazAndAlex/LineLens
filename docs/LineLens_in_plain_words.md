# LineLens, explained in plain words

*This document is for someone who has never programmed, never worked with
factory machines, and never opened a spreadsheet from a machine. If that's you,
read on — nothing here assumes any special knowledge.*

---

## The hidden problem in every factory

Modern machines record what they're doing. A machine writes down little notes
about itself — what state it's in, how long it spent there, how many items it
made, why it stopped. These notes get exported into a spreadsheet, and someone
reads the totals on a screen: "the line ran for 9 hours," "we made 4,000 parts,"
"downtime was 2 hours."

Here's the catch: **those totals can be quietly wrong**, and nobody notices,
because the numbers look precise and official.

For example, a screen might proudly show "301,492 seconds of idle time
yesterday." But a whole day only has 86,400 seconds. The number is impossible —
yet it's sitting on a dashboard that people trust.

This happens because not every number in a spreadsheet is meant to be added up.
Some are. Some really, really aren't. When the wrong kind gets added, the total
is nonsense.

## A simple analogy: the car odometer

Your car's odometer only ever goes **up**. Every mile, it ticks higher: 10,000
→ 10,001 → 10,002.

Imagine if, every hour, you wrote down the odometer reading, and then at the end
of the day you **added all those readings together**: 10,000 + 10,001 + 10,002 +
… You'd get a gigantic, meaningless number. That's not how far you drove.

The *right* way to know how far you drove is a subtraction: **last reading minus
first reading**.

A huge number of machine numbers are odometers — running totals that only go up.
And a huge number of factory dashboards accidentally add them up instead of
subtracting. That's where the impossible totals come from.

## What LineLens is

LineLens is a small, careful program that acts like a **second pair of eyes** on
a machine spreadsheet.

You give it one spreadsheet exported from a machine. It:

1. Reads it and tells you what's inside.
2. Figures out which column is the time, which is the machine state, and so on.
3. Checks whether the numbers **make sense** — do the times line up? Are there
   more seconds of "running" in a day than a day actually has? Did the machine
   log the same event twice?
4. Points to the **exact row** of every problem it finds.
5. Explains each problem **in plain language**.

When the data is clean and honest, LineLens stays quiet. When something is off,
it tells you — clearly, and with evidence.

## The one rule we never break

> **The computer does the math — and it does all of it.**

In LineLens, every number — every total, every check, every "this is wrong"
verdict — is computed by plain, testable math. There is no AI guessing in the
background, no black box handing you a number to trust on faith. If LineLens
says the idle-time total is impossible, it's because the seconds literally do
not add up.

That rule shapes how LineLens looks ahead, too. When it sketches where
production is heading, it never hands you a single confident prediction. It
draws the trend the math can see, and shades a band around it to show how much
is genuinely uncertain. And when it asks "what if we cut this stop cause?", it
recomputes the totals from the same fixed formulas — move a lever, watch the
honest numbers move with it. The math is the whole instrument; the human just
reads what it worked out.

## What LineLens can do today

Here's what has actually been built so far, in plain terms:

- **A clean workspace.** The project is set up and organized, with instructions
  that tell any helper (human or AI) exactly how to work on it safely.
- **It can open a spreadsheet.** It handles common messiness: different
  separator characters, files saved on foreign computers, hidden header
  characters, and columns that contain text where numbers were expected.
- **It can describe a spreadsheet.** It tells you how many rows there are, what
  the columns are called, and what kind of data each column holds.
- **It can match up the columns.** Every machine calls things by different names
  ("State," "Status," "Machine_State"...). LineLens figures out which column is
  which role — the time, the state, the counts — and can even guess when the
  names are unusual.
- **It checks the data for common mistakes** and flags each one:
  - times that are missing, out of order, or duplicated;
  - an end time that comes *before* its start time;
  - the same record listed twice (a copy-paste error);
  - events that overlap in time, as if the machine were in two places at once;
  - a "duration" that doesn't match the start and end times;
  - **more seconds of a machine state in one day than a day has (86,400)** — the
    impossible-total problem;
  - machine states it doesn't recognize;
  - a "stopped" machine with no reason given, or a "running" machine that oddly
    carries a stop reason.
- **For every problem, it gives the exact row number**, so a person can open the
  spreadsheet and see the trouble for themselves.

Each of these checks is backed by an automatic test, so we know it actually
catches what it claims to catch.

## How the program is organized

Think of the program as a building with separate rooms, one per job:

- one room **opens files**,
- one room **matches columns**,
- one room **checks times**,
- one room **checks durations**,
- one room **checks machine states**.

Keeping jobs in separate rooms means each piece is small, trustworthy, and easy
to fix without breaking the others. Nothing is allowed to quietly change the
original data — the spreadsheet you gave in is never altered.

## What comes next (the hard part)

The odometer problem. Telling a "running total" column apart from other columns,
handling the moment it resets to zero, and computing the **honest** total
instead of the inflated one.

This is subtle enough that, before building it, we **wrote out the full plan and
had it checked and criticized** — the way a builder double-checks a blueprint
before pouring concrete. (See `docs/m4-counter-design.md` for that blueprint.)

## In one sentence

LineLens is a careful, plain-spoken checker for machine spreadsheets: it does
the math itself, finds the numbers that don't add up, and explains — in human
words — exactly where the spreadsheet is misleading you.
