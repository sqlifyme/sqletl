import itertools
import pandas


class DataTable:
    def __init__(self, cols=None, rows=None, source=None):
        if isinstance(cols, DataTable):
            self.set_columns(cols.cols, source)
        else:
            self.set_columns(cols or [], source)
        if rows is None:
            rows = []
        self.rows = iter(rows)
        self.started = False
        self.stopped = False
        self.count = 0

    def set_columns(self, cols, source=None):
        self.cols = []
        self.add_columns(cols, source)
    
    def add_columns(self, cols, source=None):
        self.cols += [(source, c) if not isinstance(c, tuple) else c for c in cols]
        self.refresh_indexes()
    
    def set_source(self, source):
        for i, (src, col) in enumerate(self.cols):
            self.cols[i] = (source, col)
        self.refresh_indexes()

    def rename_source(self, prev, name):
        for i, (source, col) in enumerate(self.cols):
            if source == prev:
                self.cols[i] = (name, col)
        self.refresh_indexes()

    def refresh_indexes(self):
        self.idx_by_sources = {}
        self.idx_by_unique_names = {}
        self.source_by_unique_names = {}
        self.colnames = [c[1] for c in self.cols]
        self.prefixed_cols = []
        for i, (src, col) in enumerate(self.cols):
            self.idx_by_sources.setdefault(src, {})[col] = i
            self.idx_by_unique_names.setdefault(col, i)
            self.source_by_unique_names[col] = src
            self.prefixed_cols.append(src + '__' + col if src else col)

    def colidx(self, col, source=None):
        if source:
            return self.idx_by_sources[source][col]
        return self.idx_by_unique_names[col]

    def get(self, row, col, source=None):
        return row[self.colidx(col, source)]
    
    def peek(self):
        try:
            row, self.rows = iter_peek(self.rows)
        except StopIteration:
            row = None
            self.rows = []
        return row

    def is_empty(self):
        if self.started:
            return self.count == 0
        try:
            _, self.rows = iter_peek(self.rows)
            return False
        except StopIteration:
            return True
        
    def __iter__(self):
        return self
    
    def __next__(self):
        self.started = True
        try:
            row = self._next_row()
            self.count += 1
            return row
        except StopIteration:
            self.stopped = True
            raise

    def _next_row(self):
        row = next(self.rows)
        if len(row) < len(self.cols):
            return row + (None,) * (len(self.cols) - len(row))
        return row
    
    def to_dict(self):
        colnames = list(self.idx_by_unique_names.items())
        return [{c: row[i] for c, i in colnames} for row in self]
    
    def to_dataframe(self):
        return pandas.DataFrame(iter(self), columns=self.colnames)
    
    def __getstate__(self):
        return self.cols, list(self)
    
    def __setstate__(self, state):
        self.cols = state[0]
        self.refresh_indexes()
        self.rows = iter(state[1])
        self.started = False
        self.stopped = False
        self.count = 0


class PandasDataTable(DataTable):
    def __init__(self, df, source=None):
        self.dataframe = df
        super().__init__(list(df.columns), df.values, source)

    def to_dict(self):
        return self.dataframe.to_dict('records')

    def to_dataframe(self):
        return self.dataframe


class DictDataTable(DataTable):
    def __init__(self, rows, cols=None, source=None):
        if not cols:
            try:
                first, self.rows = iter_peek(iter(rows))
                cols = list(first.keys())
            except StopIteration:
                cols = []
                self.rows = iter([])
        else:
            self.rows = iter(rows)
        if isinstance(cols, DataTable):
            self.set_columns(cols.cols, source)
        else:
            self.set_columns(cols, source)
        self.started = False
        self.stopped = False
        self.count = 0

    def _next_row(self):
        row = next(self.rows)
        return tuple(row.get(k) for _, k in self.cols)
    
    def to_dict(self):
        return self.rows
    
    def __getstate__(self):
        return self.cols, self.rows
    

def iter_peek(it):
    item = next(it)
    return item, itertools.chain([item], it)