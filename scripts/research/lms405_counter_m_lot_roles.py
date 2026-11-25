"""Project counter-M exit quantities under explicit long-lot role assumptions."""

import argparse
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import verified_json
from lms_near405_replay import encoded, sha

DECEMBER = Path("output/lms405-jm2601-structure-20261125/m-window-verified.json")
DECEMBER_SHA = "44d2374be78820702e898454288a46632edf69713cd1855c5c42ed37ed96ba0e"
OCTOBER = Path("output/lms405-jm-m-leg-handoff-20261125/final.json")
OCTOBER_SHA = "3f768f34ccacc10739ef168aa119f3b5d6beb8c2fbf6ebe4d31e5caa787719ae"
RETENTION = Path("output/lms405-portfolio-retention-prices-20261126/final-a.json")
RETENTION_SHA = "6dffbea40a4f4b8763794555902ac1f33ba1d00cc1e70f9f46bac0f2dc605364"


def exposure(position):
    return dict(long=position.long, short=position.short, net=position.long - position.short,
                gross=position.long + position.short)


def exit_projection(contract, visible_longs, assumed_shorts, designated_m_longs):
    """Close only the designated long lots in a hypothetical account position."""
    visible, short, exiting = map(Decimal, (visible_longs, assumed_shorts, designated_m_longs))
    before = Position(contract, visible, short)
    after = apply_action(before, Action("EXIT_LONG", exiting)) if exiting else before
    return dict(designated_m_longs=exiting, before=exposure(before), after=exposure(after))


def compare_roles(contract, visible_longs, prior_shorts, retained_counts):
    if not retained_counts or any(not 0 <= old <= visible_longs for old in retained_counts):
        raise ValueError("LMS_M_LOT_RETENTION_INVALID")
    return dict(
        # A new lot may still have a protection role. These branches deliberately
        # assign roles as hypotheses rather than deriving them from lot age.
        new_longs_only_are_m_original_short_still_held=[
            dict(older_longs=old) | exit_projection(contract, visible_longs, prior_shorts, visible_longs - old)
            for old in retained_counts
        ],
        all_longs_are_m_original_short_still_held=exit_projection(
            contract, visible_longs, prior_shorts, visible_longs,
        ),
        all_longs_are_m_original_short_already_closed=exit_projection(
            contract, visible_longs, 0, visible_longs,
        ),
    )


def check_images(*photos):
    for photo in photos:
        image = photo["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("LMS_M_LOT_IMAGE_CHANGED")


def retention_row(report, contract, before, after, side):
    (row,) = (row for row in report["contracts"][contract]["checks"]
              if (row["before"], row["after"], row["side"]) == (before, after, side))
    return row


def study():
    december = verified_json(DECEMBER, DECEMBER_SHA)
    october = verified_json(OCTOBER, OCTOBER_SHA)
    retention = verified_json(RETENTION, RETENTION_SHA)
    dec_lots = december["added_lot_hypothesis"]
    dec_evidence = ARCHIVE.parent.parent / "lms405/evidence"
    if any(sha((dec_evidence / name).read_bytes()) != fingerprint
           for name, fingerprint in december["source_table_sha256"].items()):
        raise ValueError("LMS_M_LOT_SOURCE_TABLE_CHANGED")
    dec_sources = {key: december["sources"][key] for key in ("N01", "N02", "O02", "N05")}
    dec_contract = december["contract"]
    dec_visible = dec_lots["visible_lots"]
    dec_old = dec_lots["old_lots"]
    dec_prior_short = 20  # N01 transcription, later short is unlisted.
    if dec_contract != "JM2601" or dec_visible - dec_lots["visible_today_lots"] != dec_old:
        raise ValueError("LMS_M_LOT_DECEMBER_IDENTITY_CHANGED")
    dec_paths = compare_roles(dec_contract, dec_visible, dec_prior_short, [dec_old])

    jm = october["contract"]
    jm_first, jm_later = (october["visible"][key] for key in ("WRnTlEfj1t", "WRo00BFM1E"))
    check_images(jm_first, jm_later)
    row = retention_row(retention, jm, jm_first["source"], jm_later["source"], "long")
    if jm != "JM2701" or "short" in jm_later["legs"] or any(
        Decimal(photo["legs"]["long"]["opening_average"]) != Decimal(row[key]["opening_average"])
        or photo["legs"]["long"]["quantity"] != row[key]["quantity"]
        for photo, key in ((jm_first, "earlier_leg"), (jm_later, "later_leg"))
    ):
        raise ValueError("LMS_M_LOT_OCTOBER_IDENTITY_CHANGED")
    jm_paths = compare_roles(jm, jm_later["legs"]["long"]["quantity"],
                             jm_first["legs"]["short"]["quantity"], row["retained"])

    sh = "SH2701"
    before, day_close, after = "WRoAkcEppg", "U03", "WRoEvasxQR"
    evidence = {sid: retention["snapshot_sources"][sid] for sid in (before, day_close, after)}
    check_images(*evidence.values())
    long_leg = retention_row(retention, sh, before, after, "long")
    sh_prior = long_leg["later_leg"]["quantity"]
    if long_leg["retained"] != [0] or long_leg["later_leg"]["today_quantity"] != sh_prior:
        raise ValueError("LMS_M_LOT_SODA_CLOCK_CHANGED")
    short_leg = retention_row(retention, sh, day_close, after, "short")
    if short_leg["retained"] != [short_leg["later_leg"]["quantity"]]:
        raise ValueError("LMS_M_LOT_SODA_SHORT_IDENTITY_CHANGED")
    sh_short = short_leg["later_leg"]["quantity"]
    return dict(
        version="lms405-counter-m-lot-roles-v1", scope="CONDITIONAL_EXIT_EXPOSURE_NO_IDENTIFIED_AUTHOR_ACTION",
        cases={
            dec_contract: dict(sources=dec_sources, source_lot_constraints=dec_lots,
                               actual_later_short=None, projected=dec_paths),
            jm: dict(before=jm_first, after=jm_later, same_side_retention=row,
                     actual_later_short=None, projected=jm_paths),
            sh: dict(sources=evidence, same_side_retention=long_leg, visible_short=sh_short,
                     short_retention_from_close=short_leg,
                     projected_new_long_is_protection=exit_projection(sh, sh_prior, sh_short, 0),
                     projected_new_long_is_m=exit_projection(sh, sh_prior, sh_short, sh_prior)),
        },
        references=dict(december=DECEMBER_SHA, october=OCTOBER_SHA, retention=RETENTION_SHA),
        actual_role=None, actual_exit_at=None, actual_exit_quantity=None, author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        result = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (OSError, KeyError, ValueError):
        parser.exit(2, "LMS_M_LOT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
