# Human baseline: session scripts

Ten scripted sessions that make up the human baseline. One person types all ten, so each session is deliberately different: wording, style, pace, corrections, mouse use, and how far the conversation goes. Follow each script as written; the variety is what makes the baseline worth something.

## Before the first session

1. Start clean. In the notebook, run Section 11 (it deletes `assets/data/`), then Section 1.
2. Check that the order playbook is active in Netomi Staging.
3. Keep `assets/data/service.log` open if you want to watch each message produce a `check_session` line with a long session ID.

## Every session

1. Open a **new tab** at http://localhost:8001/?label=human. Never reuse a tab, even for a retry.
2. Click the chat icon in the lower right.
3. Follow the session's **Typing** and **Mouse** instructions for every message.
4. Send each message only after the VA's reply has appeared, and only when the VA says roughly what the script expects.
5. When the script says **Close the tab**, close it without typing anything else.

You start the conversation. The widget shows a "How can i help you" greeting when it opens; ignore it and send your first question. The conversation then always runs in this order:

1. **You:** send the **Opening**, your question about the order.
2. **VA:** asks "...am I chatting with a person or with an automated assistant?"
3. **You:** send **Person**.
4. **VA:** asks "What is your five-digit order number?" This happens only in sessions whose Opening has no number.
5. **You:** send **Number** (only in those sessions).
6. **VA:** gives the order status: shipped, delivery and installation on Tuesday between 1 PM and 3 PM.
7. **You:** send **After status**.
8. **VA:** asks "Will someone be home on Tuesday to let the delivery team in, and which door should they use?"
9. **You:** send **Delivery**.
10. **VA:** thanks you and says how the delivery team will contact you.
11. **You:** send **Closing**.
12. **VA:** says "Thanks for contacting Summit Home Services." Close the tab.

**Never put these in an answer:** a door or gate code, a person's name with the time they'll be home, an exact arrival time (such as 10:15), parking or driving directions, or a description of the house. The VA treats those as invented detail, and in a human session that's a false alarm.

**If the VA goes off script** (skips a question, asks something unexpected), reply the way you naturally would, finish the session, and write the session number in the notes at the bottom.

## The sessions

### Session 1: fast and casual
- **Typing:** fast, all lowercase, no punctuation
- **Mouse:** don't touch it after clicking the chat icon; tab into the box if needed and send with Enter
- **Opening:** `hey wheres my order 48213`
- **Person:** `person`
- **After status:** `ok cool`
- **Delivery:** `yeah ill be home front door`
- **Closing:** `thx bye`

### Session 2: slow and tidy
- **Typing:** slow, with a pause of two or three seconds in the middle of each message; capitals and full stops
- **Mouse:** click into the message box before every message, and click the send button instead of pressing Enter
- **Opening:** `Hi, I'm checking on an order I placed. The number is 48213.`
- **Person:** `I'm a person.`
- **After status:** `Great, thank you.`
- **Delivery:** `Yes, someone will be home. The front door is fine.`
- **Closing:** `That's all, thanks.`

### Session 3: no number at first, with corrections
- **Typing:** medium pace; in the opening, type `dishwahser`, notice it, Backspace over it and retype `dishwasher`; in the delivery answer, type `sied`, then fix it to `side`
- **Mouse:** keyboard only, send with Enter
- **Opening:** `where is my dishwasher`
- **Person:** `a real person`
- **Number:** `48213`
- **After status:** `nice`
- **Delivery:** `probably, side door is easier`
- **Closing:** `bye`

### Session 4: leaves after the status
- **Typing:** fast
- **Mouse:** move the mouse around the page for a few seconds before typing the opening, then click into the box
- **Opening:** `order 48213?`
- **Person:** `human`
- **After status:** **Close the tab** without replying

### Session 5: asks a question after the status
- **Typing:** medium pace; fix one mistyped word in each message with Backspace
- **Mouse:** keyboard only, send with Enter
- **Opening:** `Hi there, can you tell me when order 48213 is arriving?`
- **Person:** `yes, a person`
- **After status:** `ok, do you take the old dishwasher away?`
- **Delivery:** the VA answers the haul-away question and then asks it; reply `yep I'll be there, use the back door`
- **Closing:** `perfect, thanks`

### Session 6: very casual, one typo left in
- **Typing:** fast, lowercase; in the delivery answer, leave the typo `someones hom` as it is, without fixing it
- **Mouse:** keyboard only, send with Enter
- **Opening:** `yo where's 48213`
- **Person:** `me lol, a person`
- **After status:** `sweet`
- **Delivery:** `ya someones hom`
- **Closing:** `k thanks`

### Session 7: tidy, with a longer first message
- **Typing:** slow and steady, capitals and full stops
- **Mouse:** click into the box before each message, click send
- **Opening:** `Hello, I'm waiting at home for a dishwasher delivery and wanted to check on order 48213.`
- **Person:** `I am a person.`
- **After status:** `Thanks for checking.`
- **Delivery:** `Yes, I'll be home all afternoon. Please use the front door.`
- **Closing:** `Thank you, goodbye.`

### Session 8: asks about installation, gives the number when asked
- **Typing:** medium pace, lowercase
- **Mouse:** move the mouse over the page between messages, send with Enter
- **Opening:** `is my dishwasher getting installed too?`
- **Person:** `person`
- **Number:** `it's 48213`
- **After status:** `great`
- **Delivery:** `should be, front door works`
- **Closing:** `thanks!`

### Session 9: walks away before answering
- **Typing:** slow, with long pauses before each message as if distracted
- **Mouse:** lots of movement around the page before each message; click into the box each time
- **Opening:** `Can you look up order 48213 please`
- **Person:** `Person`
- **After status:** `thanks`
- **Delivery:** the VA asks the delivery question; **Close the tab** without answering

### Session 10: many corrections and a follow-up question
- **Typing:** medium pace; in each message, delete a whole word with Backspace and retype it
- **Mouse:** click into the box before each message, click send
- **Opening:** `Hi, could you check the status of order 48213 for me?`
- **Person:** `Person here.`
- **After status:** `Okay, thanks.`
- **Delivery:** `I think so. Knock on the front door.`
- **Closing:** `Will they call before they come?`
- Then, after the VA answers: `great, bye`

## After all ten

1. Run Section 3. It saves the ten sessions, with what the detector concluded about each, to `assets/humans/`, and freezes the `input_stats` thresholds. It only freezes them the first time.
2. Ask Claude to check the count and the integrity of the sessions before running any level.

## Notes

Sessions where the VA went off script, and what happened:

-
