FILES:
- readme.txt: This file
- explain.txt: Description of the crawler
- requirements.txt: Python packages as output by pip
- crawler.py: Source code and script for running the crawler
- brooklyn_parks_bfs.txt: Crawling output for the query "brooklyn parks" using BFS crawling
- brooklyn_parks_priority.txt: Crawling output for the query "brooklyn parks" using prioritized crawling
- paris_texas_bfs.txt: Crawling output for the query "paris texas" using BFS crawling
- paris_texas_priority.txt: Crawling output for the query "paris texas" using prioritized crawling



SYSTEM REQUIREMENTS:
- Python 3.7+
- pip: Package management
- virtualenv: Environment management, optional but recommended



INSTALLATION INSTRUCTIONS:

After installing Python and pip, run the following command in a terminal to install all package dependencies:
    $ pip install -r requirements



USAGE INSTRUCTIONS:

This is the program command-line interface description:

    $ python crawler.py -h
    Usage: crawler.py [OPTIONS] QUERY

    Options:
      -b, --bfs   Runs BFS crawler. Without this flag, the crawler runs in prioritized mode.
      -h, --help  Show this message and exit.

Examples:

    1. Crawling query "new york university" with priority score and storing output in new_york_university_priority.txt:

        $ python crawler.py "new york university" > new_york_university_priority.txt

    2. Crawling query "new york university" with BFS score and storing output in new_york_university_bfs.txt:

        $ python crawler.py --bfs "new york university" > new_york_university_bfs.txt

To print the crawling output in real-time, simply use "tail -f" with the file:
    $ tail -f new_york_university_priority.txt
