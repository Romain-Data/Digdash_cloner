# digdash_cloner/__main__.py
try:
    from .main import main
except ImportError:
    from digdash_cloner.main import main

if __name__ == "__main__":
    main()
