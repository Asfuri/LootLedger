import pytest

from lootledger.config import Config
from lootledger.detector import Detector, Observation, Target


def opening(detector, key=1, start=0, token="xp1", strong=True, kind="Unknown"):
    events = []
    for offset, closed, opened, search, progress, xp in (
            (0, .96, 0, True, .1, []), (.1, .96, 0, True, .2, []),
            (.2, .96, 0, True, .45, []), (.3, .96, 0, True, .94 if strong else .5, []),
            (.4, 0, .96, False, None, [token]), (.5, 0, .96, False, None, [token])):
        events += detector.feed(Observation(start + offset, True, [Target(key, closed, opened, kind)],
                                            search, progress, xp, focus=key))
    return events


def test_completed_opening_once_despite_lingering_notification():
    detector = Detector(Config())
    events = opening(detector)
    for index in range(6, 80):
        events += detector.feed(Observation(index / 10, True, [Target(1, 0, .96)], xp_tokens=["xp1"]))
    assert len(events) == 1
    assert events[0].status == "confirmed"
    assert events[0].chest_type == "Unknown"


def test_rapid_different_chests_without_global_cooldown():
    detector = Detector(Config())
    events = opening(detector) + opening(detector, 2, .6, "xp2")
    assert len(events) == 2
    assert all(event.status == "confirmed" for event in events)


def test_two_personal_openings_share_a_notification_that_becomes_chest_x2():
    from lootledger.vision import ChestLabel, NotificationTracker
    detector, notifications = Detector(Config()), NotificationTracker()
    events = []
    for key, start in ((1, 0), (2, .6)):
        for i, progress in enumerate((.1, .2, .45, .94, None, None)):
            stamp = round(start + i / 10, 2)
            count = 2 if stamp >= 1 else 1
            labels = [ChestLabel("CHEST", 20, 40, 80, 18, count)] if stamp >= .4 else []
            tokens = notifications.update(labels, stamp)
            closed = i < 4
            events += detector.feed(Observation(stamp, True,
                [Target(key, .96 if closed else 0, 0 if closed else .96)],
                closed, progress, tokens, focus=key))
    for i in range(12, 25):
        tokens = notifications.update([ChestLabel("CHEST X2", 20, 40, 80, 18, 2)], i / 10)
        events += detector.feed(Observation(i / 10, True, [Target(2, 0, .96)], xp_tokens=tokens))
    assert len(events) == 2
    assert all(event.status == "confirmed" for event in events)


def test_cancelled_search_and_other_container_do_not_count():
    detector = Detector(Config())
    for i in range(70):
        targets = [Target(1, .96, 0)] if i < 4 else []
        assert detector.feed(Observation(i / 10, True, targets, i < 4, .3, focus=1)) == []
    for i in range(70, 80):
        assert detector.feed(Observation(i / 10, True, [], True, 1, ["ammo-xp"])) == []


def test_generic_search_and_opened_object_without_closed_chest_are_insufficient():
    detector = Detector(Config())
    for i in range(10):
        assert detector.feed(Observation(i / 10, True, [Target(1, 0, .99)], True, 1, ["xp"], focus=1)) == []


def test_partial_progress_is_reviewable():
    assert opening(Detector(Config()), strong=False)[0].status == "review"


def test_spectating_cannot_count_or_carry_state_into_play():
    detector = Detector(Config())
    detector.feed(Observation(0, True, [Target(1, .99)], True, .1, focus=1))
    assert detector.feed(Observation(.1, False, [Target(1, .99)], True, .9, ["xp"], focus=1)) == []
    assert detector.feed(Observation(.2, True, [Target(1, 0, .99)], xp_tokens=["xp"])) == []


def test_camera_loss_and_chest_xp_do_not_confirm_an_opening():
    detector = Detector(Config())
    for i in range(5):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, i / 5, focus=1))
    for i in range(5, 65):
        events = detector.feed(Observation(i / 10, True, xp_tokens=["xp1"]))
        assert not any(event.status == "confirmed" for event in events)


def test_camera_loss_without_chest_xp_does_not_create_a_review():
    detector = Detector(Config())
    for i in range(5):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, i / 5, focus=1))
    for i in range(5, 65):
        assert detector.feed(Observation(i / 10, True)) == []


def test_lingering_xp_cannot_be_reused_for_next_chest():
    detector = Detector(Config())
    assert len(opening(detector)) == 1
    assert opening(detector, 2, .6, "xp1") == []
    assert detector.finish()[0].status == "review"


def test_notification_before_search_does_not_confirm_new_interaction():
    detector = Detector(Config())
    detector.feed(Observation(0, True, xp_tokens=["old"]))
    assert opening(detector, start=.1, token="old") == []


def test_capture_stall_breaks_temporal_proof_and_backwards_time_rejected():
    detector = Detector(Config())
    detector.feed(Observation(0, True, [Target(1, .99)], True, .1, focus=1))
    assert detector.feed(Observation(3, True, [Target(1, 0, .99)], xp_tokens=["xp"])) == []
    with pytest.raises(ValueError):
        detector.feed(Observation(2, True))


def test_search_is_bound_to_crosshair_target():
    detector = Detector(Config())
    for i in range(5):
        detector.feed(Observation(i / 10, True, [Target(1, .99), Target(2, .99)], True, i / 5, focus=1))
    assert detector.tracks[1].searched
    assert not detector.tracks[2].searched


def test_cancelled_progress_cannot_confirm_someone_elses_later_opening():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5, .95)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    for i in (4, 5):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], False, focus=1))
    for i in (6, 7, 8):
        events = detector.feed(Observation(i / 10, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
        assert not any(event.status == "confirmed" for event in events)


def test_full_search_and_chest_xp_without_opened_proof_are_review_only():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5, .95)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    events = []
    for i in range(4, 18):
        events += detector.feed(Observation(i / 10, True, xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "review"
    assert "opened state not established" in events[0].reason


def test_partial_cancelled_search_cannot_create_a_review_from_chest_xp_alone():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5, .7)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    for i in range(4, 65):
        assert detector.feed(Observation(i / 10, True, xp_tokens=["xp"])) == []


def test_xp_seen_with_a_closed_chest_before_search_cannot_confirm_it():
    detector = Detector(Config())
    detector.feed(Observation(0, True, [Target(1, .99)], xp_tokens=["old"]))
    events = opening(detector, start=.1, token="old")
    assert not any(event.status == "confirmed" for event in events)


def test_ring_reset_at_completion_preserves_a_reviewable_interaction():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .6, .84, 0)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    events = []
    for i in range(5, 18):
        events += detector.feed(Observation(i / 10, True, xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "review"


def test_ambiguous_camera_association_cannot_confirm_an_opening():
    detector = Detector(Config())
    events = []
    for i, progress in enumerate((.1, .2, .5, .95, None, None)):
        closed = i < 4
        events += detector.feed(Observation(i / 10, True,
            [Target(1, .99 if closed else 0, 0 if closed else .99, uncertain=not closed)],
            closed, progress, [] if closed else ["xp"], focus=1))
    assert len(events) == 1 and events[0].status == "review"


def test_opened_state_flicker_keeps_a_review_without_relaxing_confirmation():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5, .76, 0)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    detector.feed(Observation(.5, True, [Target(1, 0, .99)]))
    detector.feed(Observation(.6, True, [Target(1, .99)]))
    events = detector.feed(Observation(.7, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "review"
    assert events[0].time == .5


def test_an_opened_reading_across_missing_frames_is_uncertain():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5, .95)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    detector.feed(Observation(.4, True, [Target(1, 0, .99)]))
    detector.feed(Observation(.5, True))
    events = detector.feed(Observation(.6, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "review"


def test_first_progress_frame_survives_waiting_for_second_closed_observation():
    detector = Detector(Config())
    for i, progress in enumerate((.4, .7, .95)):
        detector.feed(Observation(i / 5, True, [Target(1, .99)], True, progress, focus=1))
    detector.feed(Observation(.6, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    events = detector.feed(Observation(.8, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "confirmed"


def test_brief_search_ocr_dropout_keeps_the_progress_for_review():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .32)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    for stamp in (.3, .4):
        detector.feed(Observation(stamp, True, [Target(1, .99)]))
    for stamp, progress in ((.5, .65), (.6, .95)):
        detector.feed(Observation(stamp, True, [Target(1, .99)], True, progress, focus=1))
    detector.feed(Observation(.7, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    events = detector.feed(Observation(.8, True, [Target(1, 0, .99)], xp_tokens=["xp"]))
    assert len(events) == 1 and events[0].status == "review"


def test_sustained_cancelled_search_is_not_revived_by_later_xp():
    detector = Detector(Config())
    for i, progress in enumerate((.1, .2, .5)):
        detector.feed(Observation(i / 10, True, [Target(1, .99)], True, progress, focus=1))
    for stamp in (.3, .4, .5, .6):
        detector.feed(Observation(stamp, True, [Target(1, .99)]))
    for stamp in (.7, .8):
        assert detector.feed(Observation(stamp, True, [Target(1, 0, .99)], xp_tokens=["xp"])) == []
