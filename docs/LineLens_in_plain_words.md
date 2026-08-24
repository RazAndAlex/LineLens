# LineLens, explained in plain words

*This document is for someone who has never programmed, never worked with
factory machines, and never opened a spreadsheet exported from one. If that is
you, read on. Nothing here assumes any special knowledge.*

## The hidden problem in every factory

Modern machines record what they are doing. A machine writes little notes about
itself: what state it is in, how long it spent there, how many items it made,
why it stopped. Those notes get exported into a spreadsheet. Someone then reads
the totals on a screen. The line ran for 9 hours. We made 4,000 parts. Downtime
was 2 hours.

Here is the catch. **Those totals can be quietly wrong**, and nobody notices,
because the numbers look precise and official.

A screen might proudly show 301,492 seconds of idle time yesterday. But a whole
day only holds 86,400 seconds. The number is impossible, and it is sitting on a
dashboard that people trust.

This happens because not every number in a spreadsheet is meant to be added up.
Some are. Some really are not. When the wrong kind gets added, the total is
nonsense.

## A simple analogy: the car odometer

Your car's odometer only ever goes **up**. Every mile it ticks higher: 10,000,
then 10,001, then 10,002.

Imagine writing down the odometer reading every hour, then **adding all those
readings together** at the end of the day. 10,000 plus 10,001 plus 10,002, and
so on. You would get a gigantic, meaningless number. That is not how far you
drove.

The right way to know how far you drove is a subtraction. Last reading minus
first reading.

A great many machine numbers are odometers, meaning running totals that only go
up. And a great many factory dashboards add them up instead of subtracting.
That is where the impossible totals come from.

## What LineLens is

LineLens is a small, careful program that acts like a **second pair of eyes** on
a machine spreadsheet.

You give it one spreadsheet exported from a machine. It reads the file and tells
you what is inside. It works out which column is the time, which is the machine
state, and so on. It checks whether the numbers make sense. Do the times line
up? Are there more seconds of running in a day than a day actually has? Did the
machine log the same event twice? It points to the exact row of every problem it
finds, and explains each one in plain language.

When the data is clean and honest, LineLens stays quiet. When something is off,
it tells you clearly, and with evidence.

## The one rule we never break

> **The computer does the math, and it does all of it.**

Every number in LineLens is computed by plain, testable arithmetic. Every total,
every check, every "this is wrong" verdict. There is no AI guessing in the
background, and no black box handing you a number to trust on faith. If LineLens
says the idle-time total is impossible, it is because the seconds literally do
not add up.

That rule shapes how LineLens looks ahead too. When it sketches where production
is heading, it never hands you a single confident prediction. It draws the trend
the math can see, and shades a band around it to show how much is genuinely
uncertain. When it asks what would happen if you cut a stop cause, it recomputes
the totals from the same fixed formulas. Move a lever, watch the honest numbers
move with it. The math is the whole instrument. The person just reads what it
worked out.

## What LineLens can do today

**It opens a messy spreadsheet.** Different separator characters, files saved on
foreign computers, hidden header characters, and columns holding text where
numbers were expected. It copes with all of them.

**It describes what it found.** How many rows there are, what the columns are
called, and what kind of data each column holds.

**It matches up the columns, and guesses first.** Every machine calls things by
different names: State, Status, Machine_State. LineLens works out which column
fills which role, and tells you what each choice unlocks before you commit.

**It checks the data for common mistakes**, and flags each one with the exact
row number so you can go and look:

- times that are missing, out of order, or duplicated
- an end time that comes *before* its start time
- the same record listed twice, which is usually a copy-paste error
- events that overlap, as if the machine were in two places at once
- a duration that does not match the start and end times
- **more seconds of a machine state in one day than a day holds**, the
  impossible-total problem
- machine states it does not recognize
- a stopped machine with no reason given, or a running machine that oddly
  carries a stop reason

**It solves the odometer problem.** This was the hard part, and it is done.
LineLens tells a running-total column apart from an ordinary one, handles the
moment a counter resets to zero, and computes the honest total instead of the
inflated one. It then shows you both numbers side by side, because the gap
between them is the whole point.

**It prices every stop in product.** Time lost to a stop cause, multiplied by
the speed the line should have been running. Now the argument about where to
spend the next maintenance hour has a number attached.

**It computes OEE**, the standard factory score, broken into its three parts:
how much of the time the line was available, how fast it ran when it was
running, and how much of what it made was good.

**It looks ahead, carefully.** It projects daily output forward as a band rather
than a single number, and it estimates when the next service falls due from how
much the line has produced since the last one. Every future quantity is a range.
None of them is a promise.

**It lets you ask what if.** Shrink a stop cause by some percentage and watch
the OEE and the output move with it, recomputed from the same formulas.

Every one of these checks is backed by an automatic test, so we know it catches
what it claims to catch.

## How the program is organized

Think of the program as a building with separate rooms, one per job. One room
opens files. One room matches columns. One room checks times. One room checks
durations and machine states. One room does the counter arithmetic. One room
draws the charts.

Keeping jobs in separate rooms means each piece stays small, trustworthy, and
easy to fix without breaking the others. Nothing is allowed to quietly change
the original data. The spreadsheet you handed in is never altered.

## What this is not

LineLens does not connect to a machine. You export a file and give it the file.

It does not predict a failure before it happens. It says when the next service
is due based on how much the line has produced, which is a different and more
modest claim.

It is not production software. It runs on your own computer, for one person, and
it has no accounts or passwords.

## In one sentence

LineLens is a careful, plain-spoken checker for machine spreadsheets. It does
the math itself, finds the numbers that do not add up, and explains in human
words exactly where the spreadsheet is misleading you.
