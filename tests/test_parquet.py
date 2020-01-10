from hypothesis import given, settings
import hypothesis.strategies as hs
import dask.dataframe as dd
import pandas as pd
from spatialpandas import GeoSeries, GeoDataFrame
from spatialpandas.dask import DaskGeoDataFrame
from tests.geometry.strategies import (
    st_multipoint_array, st_multiline_array,
    st_point_array, st_bounds)
import numpy as np
from spatialpandas.io import (
    to_parquet, read_parquet, read_parquet_dask, to_parquet_dask
)

hyp_settings = settings(deadline=None, max_examples=100)


@given(
    gp_point=st_point_array(min_size=1, geoseries=True),
    gp_multipoint=st_multipoint_array(min_size=1, geoseries=True),
    gp_multiline=st_multiline_array(min_size=1, geoseries=True),
)
@hyp_settings
def test_parquet(gp_point, gp_multipoint, gp_multiline, tmp_path):
    # Build dataframe
    n = min(len(gp_multipoint), len(gp_multiline))
    df = GeoDataFrame({
        'point': GeoSeries(gp_point[:n]),
        'multipoint': GeoSeries(gp_multipoint[:n]),
        'multiline': GeoSeries(gp_multiline[:n]),
        'a': list(range(n))
    })

    path = tmp_path / 'df.parq'
    to_parquet(df, path)
    df_read = read_parquet(path)
    assert isinstance(df_read, GeoDataFrame)
    assert all(df == df_read)


@given(
    gp_point=st_point_array(min_size=1, geoseries=True),
    gp_multipoint=st_multipoint_array(min_size=1, geoseries=True),
    gp_multiline=st_multiline_array(min_size=1, geoseries=True),
)
@hyp_settings
def test_parquet_columns(gp_point, gp_multipoint, gp_multiline, tmp_path):
    # Build dataframe
    n = min(len(gp_multipoint), len(gp_multiline))
    df = GeoDataFrame({
        'point': GeoSeries(gp_point[:n]),
        'multipoint': GeoSeries(gp_multipoint[:n]),
        'multiline': GeoSeries(gp_multiline[:n]),
        'a': list(range(n))
    })

    path = tmp_path / 'df.parq'
    to_parquet(df, path)
    columns = ['a', 'multiline']
    df_read = read_parquet(path, columns=columns)
    assert isinstance(df_read, GeoDataFrame)
    assert all(df[columns] == df_read)


@given(
    gp_multipoint=st_multipoint_array(min_size=1, geoseries=True),
    gp_multiline=st_multiline_array(min_size=1, geoseries=True),
)
@hyp_settings
def test_parquet_dask(gp_multipoint, gp_multiline, tmp_path):
    # Build dataframe
    n = min(len(gp_multipoint), len(gp_multiline))
    df = GeoDataFrame({
        'points': GeoSeries(gp_multipoint[:n]),
        'lines': GeoSeries(gp_multiline[:n]),
        'a': list(range(n))
    })
    ddf = dd.from_pandas(df, npartitions=3)

    path = tmp_path / 'ddf.parq'
    ddf.to_parquet(path)
    ddf_read = read_parquet_dask(path)

    # Check type
    assert isinstance(ddf_read, DaskGeoDataFrame)

    # Check that partition bounds were loaded
    nonempty = np.nonzero(ddf.map_partitions(len).compute() > 0)[0]
    assert set(ddf_read._partition_bounds) == {'points', 'lines'}
    expected_partition_bounds = (
        ddf['points'].partition_bounds.iloc[nonempty].reset_index(drop=True)
    )
    expected_partition_bounds.index.name = 'partition'

    pd.testing.assert_frame_equal(
        expected_partition_bounds,
        ddf_read._partition_bounds['points'],
    )

    expected_partition_bounds = (
        ddf['lines'].partition_bounds.iloc[nonempty].reset_index(drop=True)
    )
    expected_partition_bounds.index.name = 'partition'
    pd.testing.assert_frame_equal(
        expected_partition_bounds,
        ddf_read._partition_bounds['lines'],
    )

    assert ddf_read.geometry.name == 'points'

@given(
    gp_multipoint=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline=st_multiline_array(min_size=10, max_size=40, geoseries=True),
)
@settings(deadline=None, max_examples=30)
def test_pack_partitions(gp_multipoint, gp_multiline):
    # Build dataframe
    n = min(len(gp_multipoint), len(gp_multiline))
    df = GeoDataFrame({
        'points': GeoSeries(gp_multipoint[:n]),
        'lines': GeoSeries(gp_multiline[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf = dd.from_pandas(df, npartitions=3)

    # Pack partitions
    ddf_packed = ddf.pack_partitions(npartitions=4)

    # Check the number of partitions
    assert ddf_packed.npartitions == 4

    # Check that rows are now sorted in order of hilbert distance
    total_bounds = df.lines.total_bounds
    hilbert_distances = ddf_packed.lines.map_partitions(
        lambda s: s.hilbert_distance(total_bounds=total_bounds)
    ).compute().values

    # Compute expected total_bounds
    expected_distances = np.sort(
        df.lines.hilbert_distance(total_bounds=total_bounds).values
    )

    np.testing.assert_equal(expected_distances, hilbert_distances)


@given(
    gp_multipoint=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline=st_multiline_array(min_size=10, max_size=40, geoseries=True),
    use_temp_format=hs.booleans()
)
@settings(deadline=None, max_examples=30)
def test_pack_partitions_to_parquet(
        gp_multipoint, gp_multiline, use_temp_format, tmp_path
):
    # Build dataframe
    n = min(len(gp_multipoint), len(gp_multiline))
    df = GeoDataFrame({
        'points': GeoSeries(gp_multipoint[:n]),
        'lines': GeoSeries(gp_multiline[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf = dd.from_pandas(df, npartitions=3)

    path = tmp_path / 'ddf.parq'
    if use_temp_format:
        tempdir_format = str(tmp_path / 'scratch' / 'part-{uuid}-{partition:03d}')
    else:
        tempdir_format = None

    ddf_packed = ddf.pack_partitions_to_parquet(
        path, npartitions=4,
        tempdir_format=tempdir_format
    )

    # Check the number of partitions (< 4 can happen in the case of empty partitions)
    assert ddf_packed.npartitions <= 4

    # Check that rows are now sorted in order of hilbert distance
    total_bounds = df.lines.total_bounds
    hilbert_distances = ddf_packed.lines.map_partitions(
        lambda s: s.hilbert_distance(total_bounds=total_bounds)
    ).compute().values

    # Compute expected total_bounds
    expected_distances = np.sort(
        df.lines.hilbert_distance(total_bounds=total_bounds).values
    )

    np.testing.assert_equal(expected_distances, hilbert_distances)
    assert ddf_packed.geometry.name == 'points'

    # Read columns
    columns = ['a', 'lines']
    ddf_read_cols = read_parquet_dask(path, columns=columns + ['hilbert_distance'])
    pd.testing.assert_frame_equal(
        ddf_read_cols.compute(), ddf_packed[columns].compute()
    )


@given(
    gp_multipoint1=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline1=st_multiline_array(min_size=10, max_size=40, geoseries=True),
    gp_multipoint2=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline2=st_multiline_array(min_size=10, max_size=40, geoseries=True),
)
@settings(deadline=None, max_examples=30)
def test_pack_partitions_to_parquet_glob(
        gp_multipoint1, gp_multiline1,
        gp_multipoint2, gp_multiline2,
        tmp_path
):
    # Build dataframe1
    n = min(len(gp_multipoint1), len(gp_multiline1))
    df1 = GeoDataFrame({
        'points': GeoSeries(gp_multipoint1[:n]),
        'lines': GeoSeries(gp_multiline1[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf1 = dd.from_pandas(df1, npartitions=3)
    path1 = tmp_path / 'ddf1.parq'
    ddf_packed1 = ddf1.pack_partitions_to_parquet(path1, npartitions=3)

    # Build dataframe2
    n = min(len(gp_multipoint2), len(gp_multiline2))
    df2 = GeoDataFrame({
        'points': GeoSeries(gp_multipoint2[:n]),
        'lines': GeoSeries(gp_multiline2[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf2 = dd.from_pandas(df2, npartitions=3)
    path2 = tmp_path / 'ddf2.parq'
    ddf_packed2 = ddf2.pack_partitions_to_parquet(path2, npartitions=4)

    # Load both packed datasets with glob
    ddf_globbed = read_parquet_dask(tmp_path / "ddf*.parq", geometry="lines")

    # Check the number of partitions (< 7 can happen in the case of empty partitions)
    assert ddf_globbed.npartitions <= 7

    # Check contents
    expected_df = pd.concat([ddf_packed1.compute(), ddf_packed2.compute()])
    df_globbed = ddf_globbed.compute()
    pd.testing.assert_frame_equal(df_globbed, expected_df)

    # Check partition bounds
    expected_bounds = {
        'points': pd.concat([
            ddf_packed1._partition_bounds['points'],
            ddf_packed2._partition_bounds['points'],
        ]).reset_index(drop=True),
        'lines': pd.concat([
            ddf_packed1._partition_bounds['lines'],
            ddf_packed2._partition_bounds['lines'],
        ]).reset_index(drop=True),
    }
    expected_bounds['points'].index.name = 'partition'
    expected_bounds['lines'].index.name = 'partition'
    pd.testing.assert_frame_equal(
        expected_bounds['points'], ddf_globbed._partition_bounds['points']
    )

    pd.testing.assert_frame_equal(
        expected_bounds['lines'], ddf_globbed._partition_bounds['lines']
    )

    assert ddf_globbed.geometry.name == 'lines'


@given(
    gp_multipoint1=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline1=st_multiline_array(min_size=10, max_size=40, geoseries=True),
    gp_multipoint2=st_multipoint_array(min_size=10, max_size=40, geoseries=True),
    gp_multiline2=st_multiline_array(min_size=10, max_size=40, geoseries=True),
    bounds=st_bounds(),
)
@settings(deadline=None, max_examples=30)
def test_pack_partitions_to_parquet_list_bounds(
        gp_multipoint1, gp_multiline1,
        gp_multipoint2, gp_multiline2,
        bounds, tmp_path,
):
    # Build dataframe1
    n = min(len(gp_multipoint1), len(gp_multiline1))
    df1 = GeoDataFrame({
        'points': GeoSeries(gp_multipoint1[:n]),
        'lines': GeoSeries(gp_multiline1[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf1 = dd.from_pandas(df1, npartitions=3)
    path1 = tmp_path / 'ddf1.parq'
    ddf_packed1 = ddf1.pack_partitions_to_parquet(path1, npartitions=3)

    # Build dataframe2
    n = min(len(gp_multipoint2), len(gp_multiline2))
    df2 = GeoDataFrame({
        'points': GeoSeries(gp_multipoint2[:n]),
        'lines': GeoSeries(gp_multiline2[:n]),
        'a': list(range(n))
    }).set_geometry('lines')
    ddf2 = dd.from_pandas(df2, npartitions=3)
    path2 = tmp_path / 'ddf2.parq'
    ddf_packed2 = ddf2.pack_partitions_to_parquet(path2, npartitions=4)

    # Load both packed datasets with glob
    ddf_read = read_parquet_dask(
        [tmp_path / "ddf1.parq", tmp_path / "ddf2.parq"],
        geometry="points", bounds=bounds
    )

    # Check the number of partitions (< 7 can happen in the case of empty partitions)
    assert ddf_read.npartitions <= 7

    # Check contents
    xslice = slice(bounds[0], bounds[2])
    yslice = slice(bounds[1], bounds[3])
    expected_df = pd.concat([
        ddf_packed1.cx_partitions[xslice, yslice].compute(),
        ddf_packed2.cx_partitions[xslice, yslice].compute()
    ])
    df_read = ddf_read.compute()
    pd.testing.assert_frame_equal(df_read, expected_df)

    # Compute expected partition bounds
    points_bounds = pd.concat([
        ddf_packed1._partition_bounds['points'],
        ddf_packed2._partition_bounds['points'],
    ]).reset_index(drop=True)

    x0, y0, x1, y1 = bounds
    x0, x1 = (x0, x1) if x0 <= x1 else (x1, x0)
    y0, y1 = (y0, y1) if y0 <= y1 else (y1, y0)
    partition_inds = ~(
        (points_bounds.x1 < x0) |
        (points_bounds.y1 < y0) |
        (points_bounds.x0 > x1) |
        (points_bounds.y0 > y1)
    )
    points_bounds = points_bounds[partition_inds].reset_index(drop=True)

    lines_bounds = pd.concat([
        ddf_packed1._partition_bounds['lines'],
        ddf_packed2._partition_bounds['lines'],
    ]).reset_index(drop=True)[partition_inds].reset_index(drop=True)
    points_bounds.index.name = 'partition'
    lines_bounds.index.name = 'partition'

    # Check partition bounds
    pd.testing.assert_frame_equal(
        points_bounds, ddf_read._partition_bounds['points']
    )

    pd.testing.assert_frame_equal(
        lines_bounds, ddf_read._partition_bounds['lines']
    )

    # Check active geometry column
    assert ddf_read.geometry.name == 'points'
