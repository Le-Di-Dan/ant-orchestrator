FROM python:3.11
COPY wheels/ /wheels/
RUN pip install --no-index --find-links=/wheels \
        pytest==9.1.1 colorama iniconfig packaging pluggy pygments \
    && rm -rf /wheels
