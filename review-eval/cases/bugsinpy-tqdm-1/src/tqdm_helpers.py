def tqdm(iterable, **kwargs):
    return iterable


def tenumerate(iterable, start=0, total=None, tqdm_class=tqdm, **kwargs):
    if total is None:
        try:
            total = len(iterable)
        except TypeError:
            total = None
    return enumerate(tqdm_class(iterable, total=total, start=start, **kwargs))
