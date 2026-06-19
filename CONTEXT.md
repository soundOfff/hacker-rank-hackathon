# Multi-Modal Evidence Review

The shared language for the HackerRank Orchestrate claim-verification challenge: a
system that decides whether submitted images support a user's damage claim, given a
chat transcript, user history, and minimum evidence requirements. This file is a
glossary only — no implementation details.

## Language

### Core claim

**Claim** (a.k.a. Damage Claim):
One row of input — a user asserting that a `claim_object` has a specific damage,
backed by one or more images and a chat transcript.
_Avoid_: case, ticket, request.

**Claim Object**:
The thing being claimed about — exactly one of `car`, `laptop`, `package`.
_Avoid_: item, product, subject.

**Claim Intent**:
The canonical, language-normalized statement of what the user is actually
claiming — the relevant object part(s) and issue type(s) — extracted from the
(possibly multilingual) chat transcript. The output of claim extraction.
_Avoid_: the claim text, the conversation.

**Claim Status**:
The final verdict on whether the images back the claim: `supported`,
`contradicted`, or `not_enough_information`. The images are the source of truth.
_Avoid_: result, outcome, decision (when precision matters).

### Evidence and image quality

**Evidence Standard Met**:
Whether the image *set* is sufficient to evaluate *this specific claim* — i.e. the
claimed part is visible from an angle/clarity that lets the claimed condition be
judged, per the `evidence_requirements`. A claim can fail this even when the
images themselves are fine (e.g. a clear photo of the wrong part).
_Avoid_: enough evidence, sufficient images (informal).

**Valid Image**:
Whether the image set is usable as an authentic, reviewable basis for automated
review at all. Distinct from Evidence Standard Met: an image can be *valid but
insufficient* (real photo, wrong part) or *invalid but still judgeable* (a
watermarked/non-original render clear enough to contradict the claim). Driven by
authenticity and basic usability, not by whether it matches the claim.
_Avoid_: good image, real image.

**Supporting Image**:
An image whose content actually backs the chosen Claim Status, identified by image
ID (filename without extension, e.g. `img_1`). `none` when no single image suffices.
_Avoid_: best image, main image.

### Issue, part, severity

**Issue Type**:
The visible damage category (`dent`, `scratch`, `crack`, `glass_shatter`,
`broken_part`, `missing_part`, `torn_packaging`, `crushed_packaging`,
`water_damage`, `stain`, `none`, `unknown`). `none` = part visible and undamaged;
`unknown` = cannot be determined.

**Object Part**:
The relevant part of the claim object, drawn from the per-object allowed list
(e.g. car `rear_bumper`, laptop `hinge`, package `seal`). `unknown` when
indeterminable.

**Severity**:
Estimated damage magnitude: `none`, `low`, `medium`, `high`, or `unknown`.

### Risk flags

**Risk Flag**:
A semicolon-separated signal attached to a claim, or `none`. Drawn from a fixed
vocabulary spanning image-quality issues, claim/image mismatches, authenticity
concerns, and history/process signals.

**Text Instruction Present**:
A risk flag for instruction-like or manipulative text that tries to steer the
decision — present in **either** the image **or** the chat transcript. Such text
is treated as untrusted data and ignored; it never moves Claim Status toward the
user's favor. Pairs with **Manual Review Required**.
_Avoid_: prompt injection (informal), instruction text (when the flag is meant).

**Claim Mismatch**:
A risk flag: the visible evidence contradicts or fails to match what was claimed
(wrong damage, wrong severity, different object than described).

**Non-original Image**:
A risk flag: the image is not an authentic first-party photo (e.g. stock/render,
visible watermark). Bears on **Valid Image**, not necessarily on whether damage is
visible.
_Avoid_: fake image.

**Possible Manipulation**:
A risk flag for signs the image itself was digitally altered/tampered. Distinct
from **Text Instruction Present** (which is about overlaid instruction text, not
pixel tampering).

**User History Risk**:
A risk flag derived from `user_history` (e.g. prior exaggeration, repeated
rejected claims). Adds context but, by itself, must not override clear visual
evidence.

**Manual Review Required**:
A risk flag marking the claim for human review (low confidence, mismatch,
manipulation/instruction signals, or risky history).
