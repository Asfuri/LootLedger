import sys

if __name__ == "__main__":
    # The retired screen detector's tools stay available from source:
    #   python -m lootledger.analyze ...   and   python -m lootledger.replay ...
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        from lootledger.smoke import main
        raise SystemExit(main(sys.argv[2]))
    from lootledger.app import main
    raise SystemExit(main())
