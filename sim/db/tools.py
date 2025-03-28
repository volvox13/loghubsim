# -*- coding: utf-8 -*-

"""
作者：Ted
日期：
说明：

处理与数据库的交互

data will be store into dictionary

"""

from os.path import join, isfile
from functools import wraps
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from collections import defaultdict

from sim.config import *


__all__ = ['write_redis', 'load_from_redis', 'write_mysql', 'write_local', 'load_from_local',
           'load_from_mysql', 'get_vehicles', 'get_unload_setting', 'get_reload_setting', 'get_resource_limit',
           'get_resource_equipment_dict', 'get_pipelines', 'get_queue_io', 'get_equipment_process_time',
           'get_parameters', 'get_resource_timetable', 'get_equipment_timetable',
           'get_equipment_store_dict', 'get_equipment_on_off', 'get_base_equipment_io_max',
           'get_equipment_port_type', 'load_last_result_table']


def checking_pickle_file(table_name):
    """checking pkl table exists"""
    return isfile(join(SaveConfig.DATA_DIR, f"{table_name}.pkl"))


def checking_h5_store(table_name):
    """checking table exists in hdf5"""
    if isfile(SaveConfig.HDF5_FILE):
        with pd.HDFStore(SaveConfig.HDF5_FILE) as store:
            return True if store.get_node(table_name) else False
    else:
        return False


def load_cache(cache_type: bool=None):
    """decorator: cache"""

    def decorator(func):
        @wraps(func)
        def wrapper(table_name):

            if cache_type == 'redis':
                if RedisConfig.CONN.exists(table_name):
                    return load_from_redis(table_name)
                else:
                    table = func(table_name)
                    write_redis(table_name, data=table)
                    return table
            elif cache_type == 'hdf5':
                if not checking_h5_store(table_name):
                    table = func(table_name)
                    write_local(table_name, data=table, is_out=False, data_format='hdf5')
                    return table
                else:
                    return load_from_hfd5(table_name)
            elif cache_type == 'pkl':
                if not checking_pickle_file(table_name):
                    table = func(table_name)
                    write_local(table_name, data=table, is_out=False, data_format='pkl')
                    return table
                else:
                    return load_from_local(table_name, is_csv=False)
            elif not cache_type:
                return func(table_name)
            else:
                ValueError("cache_type value do not expected!")
        return wrapper
    return decorator


def write_redis(table_name: str, data: pd.DataFrame,):
    """写入Redis， 设置过期时间为 24小时"""
    data_seq = data.to_msgpack()

    try:
        result = RedisConfig.CONN.setex(table_name, time=24 * 60 * 60, value=data_seq)

        if result:
            LOG.logger_font.info(f"Redis write table {table_name} succeed!")
        else:
            LOG.logger_font.info(f"Redis: table {table_name} already exist!")

    except Exception as exc:
        LOG.logger_font.error(f"Redis write table {table_name} failed, error: {exc}.")
        raise Exception


def load_from_hfd5(table_name: str):
    LOG.logger_font.info(msg=f"Reading hdf5 {table_name}")
    return pd.read_hdf(SaveConfig.HDF5_FILE, table_name)


def load_from_redis(table_name: str):
    LOG.logger_font.info(msg=f"Reading Redis {table_name}")
    data_seq = RedisConfig.CONN.get(table_name)
    return pd.read_msgpack(data_seq)


def write_mysql(table_name: str, data: pd.DataFrame, dtype: dict=None):
    """写入MySQl数据库, 表格如果存在, 则新增数据"""
    try:
        data.to_sql(name=f'o_{table_name}',
                    con=RemoteMySQLConfig.engine,
                    if_exists='append',
                    index=0,
                    dtype=dtype)

        LOG.logger_font.debug(f"mysql write table {table_name} succeed!")
    except Exception as exc:
        LOG.logger_font.error(f"mysql write table {table_name} failed, error: {exc}.")
        raise Exception


def write_local(table_name: str, data: pd.DataFrame, is_out:bool = True, data_format:str='csv'):
    """写入本地"""

    out_dir = SaveConfig.OUT_DIR if is_out else SaveConfig.DATA_DIR
    try:
        if data_format == 'csv':
            data.to_csv(join(out_dir, f"{table_name}.csv"), index=0)
        elif data_format == 'pkl':
            data.to_pickle(join(out_dir, f"{table_name}.pkl"), )
        elif data_format == 'hdf5':
            data.to_hdf(SaveConfig.HDF5_FILE, table_name)
        else:
            raise ValueError('data_format is not right!')
        LOG.logger_font.info(f"{data_format} write table {table_name} succeed!")
    except Exception as exc:
        LOG.logger_font.error(f"{data_format} write table {table_name} failed, error: {exc}.")
        raise Exception


def load_from_local(table_name: str, is_csv:bool=True):
    """本地读取数据，数据格式为csv"""
    LOG.logger_font.info(msg=f"Reading local table {table_name}")
    if is_csv:
        table = pd.read_csv(join(SaveConfig.DATA_DIR, f"{table_name}.csv"),)
    else:
        table = pd.read_pickle(join(SaveConfig.DATA_DIR, f"{table_name}.pkl"), )
    return table


@load_cache(cache_type=MainConfig.CACHE_TYPE)
def load_from_mysql(table_name: str):
    """读取远程mysql数据表"""
    LOG.logger_font.info(msg=f"Reading mysql table {table_name}")
    table = pd.read_sql_table(con=RemoteMySQLConfig.engine, table_name=f"{table_name}")
    return table


def load_last_result_table(table_name: str):
    """读取远程mysql结果数据表"""
    assert table_name in ["o_machine_table", "o_truck_table", "o_path_table", "o_pipeline_table"]
    LOG.logger_font.info(msg=f"Reading mysql table {table_name}")

    last_run_time = pd.read_sql_query(con=RemoteMySQLConfig.engine,
                                      sql=f"SELECT max(run_time) FROM {table_name}")

    last_run_time_str = last_run_time.values[0][0]
    last_run_time_str = pd.to_datetime(last_run_time_str)
    last_run_time_str = last_run_time_str.strftime(format="%Y-%m-%d %H:%M:%S")

    result = pd.read_sql_query(con=RemoteMySQLConfig.engine,
                               sql=f"SELECT * FROM {table_name} where run_time = '{last_run_time_str}'")
    return result


def get_trucks(is_test: bool=False):
    """
    返回货车数据，字典形式：
        key 为 （货车编号， 到达时间，货车货物路径类型（L／A..））
        value 为 一个货车的 packages 数据表
    """
    table_name = "i_od_parcel_landside"
    table = load_from_mysql(table_name)
    if is_test:
        table = table.head(100)

    # convert datetime to seconds

    table["arrive_time"] = (table["arrive_time"] - TimeConfig.ZERO_TIMESTAMP)\
        .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0.01)
    # 'plate_num' 是货车／飞机／的编号
    return dict(list(table.groupby(['plate_num', 'arrive_time', 'src_type'])))


def get_vehicles(is_land: bool,
                 is_test: bool,
                 is_parcel_only: bool = False,):
    """
    Returns ULD or truck data in dictionary form:

    parcel_dict:
        key: (truck number, arrival time, truck cargo path type (L/A...))
        value: a data table of packages for a ULD

    small_dict:
        key: parcel_id
        value: a data table of packages for a small bag
    """
    if is_land:
        table_parcel_n = "i_od_parcel_landside"
        table_small_n = "i_od_small_landside"
    else:
        table_parcel_n = "i_od_parcel_airside"
        table_small_n = "i_od_small_airside"

    table_parcel = load_from_mysql(table_parcel_n)
    table_small = load_from_mysql(table_small_n)

    # filter only parcel
    if is_parcel_only:
        table_parcel = table_parcel[table_parcel.parcel_type != 'small']

    # take samples for test
    if is_test:
        # keep both LL/AA
        table_parcel1 = table_parcel[table_parcel.parcel_type == 'small'].sample(250)
        table_parcel2 = table_parcel[table_parcel.parcel_type == 'nc'].sample(125)
        table_parcel3 = table_parcel[table_parcel.parcel_type == 'parcel'].sample(125)
        table_parcel = table_parcel1.append(table_parcel2).append(table_parcel3)
        # filter small

    # fixme: using parcel_id as plate_num, cos lack of plate_num for uld
    if not is_land:
        table_parcel["plate_num"] = table_parcel["parcel_id"]
        table_small["plate_num"] = table_small["parcel_id"]

    # 转换时间
    table_parcel["arrive_time"] = (pd.to_datetime(table_parcel["arrive_time"]) - TimeConfig.ZERO_TIMESTAMP) \
        .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)

    table_small["arrive_time"] = (pd.to_datetime(table_small["arrive_time"]) - TimeConfig.ZERO_TIMESTAMP) \
        .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)

    table_small = table_small[table_small["parcel_id"].isin(table_parcel.parcel_id)]
    parcel_counts = len(table_parcel['parcel_id'].unique())
    small_counts = len(table_small['small_id'].unique())

    LOG.logger_font.info(f"IS_LAND: {is_land}, input data, parcel counts: {parcel_counts}, small packages: {small_counts}")

    # 'plate_num' 是货车／飞机／的编号
    parcel_dict = dict(list(table_parcel.groupby(['plate_num', 'arrive_time', 'src_type', ])))
    small_dict = dict(list(table_small.groupby(['parcel_id'])))
    return parcel_dict, small_dict


def get_unload_setting():
    """
    Returns a dictionary mapping:
        unload port and truck types (LL, LA, AA, AL)
    examples:
        {'r1_1': ['LL', 'LA'], 'r3_1': ['LL', ]}
    """

    table_name = "i_unload_setting"
    table = load_from_mysql(table_name)
    table['truck_type'] = table['origin_type'] + table['dest_type']
    table_dict= \
        table.groupby('equipment_port')['truck_type'].apply(set).apply(list).to_dict()
    return table_dict


def get_reload_setting():
    """
    返回字典形式：
        dest_code 和 reload port 类型的映射
    examples:
        { （"571J"， "reload", ""L""): ["c1_1", ],  （"571K"， "small_sort", "L"): ["c2_3", "c2_5"] }
    """

    table_name = "i_reload_setting"
    table = load_from_mysql(table_name)
    table_dict= \
        table.groupby(['ident_des_zno', 'sorter_type', 'dest_type'])['equipment_port'].apply(set).apply(list).to_dict()
    return table_dict


def get_resource_limit():
    """Returns a resource table, including the processing time for individual resources."""

    table_name2 = "i_equipment_resource"

    table1 = get_base_resource_limit()
    table2 = load_from_mysql(table_name2)
    table3 = get_base_equipment_io()

    table2 = table2[["resource_id", "equipment_id"]].drop_duplicates()
    table3 = table3[["equipment_id", "process_time"]].drop_duplicates()

    table_temp = table2.merge(table3, how="left", on="equipment_id")
    table_temp = table_temp

    table_temp2 = table_temp.groupby(["resource_id"])["process_time"].unique().apply(
        lambda x: x[0] if len(x) == 1 else None)
    table_temp2 = table_temp2.to_frame("process_time").reset_index()

    table = table1.merge(table_temp2, how="left", on="resource_id")

    # checking merge correct
    assert table1.shape[0] == table.shape[0]
    return table


def get_resource_equipment_dict():
    """返回资源和设备槽口的对应关系"""
    table_name = "i_equipment_resource"
    table = load_from_mysql(table_name)

    table_dict = dict()

    for _, row in table.iterrows():
        table_dict[row["equipment_port"]] = row["resource_id"]

    return table_dict


def get_pipelines():

    """Returns a table of queues, including the functional area and transmission time for each queue."""

    tab_n_queue_io = "i_queue_io"
    tab_queue_io = load_from_mysql(tab_n_queue_io)
    line_count_ori = tab_queue_io.shape[0]

    equipment_store_dict = get_equipment_store_dict()
    equipment_shared_store = set([x[1]for x in equipment_store_dict.keys()])

    # add machine_type
    # m: presort
    # i1 - i8: secondary_sort
    # i17 - i24: secondary_sort
    # u1 - u8: small_primary
    # i9 - i16: small_secondary
    # c5 - c12: small_reload
    # j: security
    # h: hospital
    # e, x: cross

    # match with the small sort..
    ind_small_primary = tab_queue_io.equipment_port_next.str.startswith('u')
    ind_small_secondary = \
        tab_queue_io.equipment_port_next.apply(lambda x: x.split('_')[0]).isin([f'i{n}' for n in range(9, 17)])
    ind_small_reload = \
        tab_queue_io.equipment_port_next.apply(lambda x: x.split('_')[0]).isin([f'c{n}' for n in range(5, 13)])

    secon_sort_mark1 = [f'i{n}' for n in range(1, 9)]
    secon_sort_mark2 = [f'i{n}' for n in range(17, 25)]
    secon_sort_mark = secon_sort_mark1 + secon_sort_mark2

    ind_presort = tab_queue_io.equipment_port_next.str.startswith('m')
    ind_secondary_sort = tab_queue_io.equipment_port_next.apply(lambda x: x.split('_')[0]).isin(secon_sort_mark)
    ind_security = tab_queue_io.equipment_port_next.str.startswith('j')
    ind_hospital = tab_queue_io.equipment_port_next.str.startswith('h')
    ind_cross = \
        tab_queue_io.equipment_port_next.str.startswith('e') | tab_queue_io.equipment_port_next.str.startswith('x')

    # Treat i-i, i-c, i-e as conveyors that require resource requests
    ind_pipeline_res = \
        tab_queue_io.equipment_port_last.str.startswith('i') & \
        (tab_queue_io.equipment_port_next.str.startswith('c') | tab_queue_io.equipment_port_next.str.startswith('i')\
        | tab_queue_io.equipment_port_next.str.startswith('e'))

    ind_pipeline_replace = \
        tab_queue_io.equipment_port_next.isin(equipment_shared_store)

    tab_queue_io.loc[ind_presort, "machine_type"] = "presort"
    tab_queue_io.loc[ind_secondary_sort, "machine_type"] = "secondary_sort"

    tab_queue_io.loc[ind_small_primary, "machine_type"] = "small_primary"
    tab_queue_io.loc[ind_small_secondary, "machine_type"] = "small_secondary"
    tab_queue_io.loc[ind_small_reload, "machine_type"] = "small_reload"

    tab_queue_io.loc[ind_security, "machine_type"] = "security"
    tab_queue_io.loc[ind_cross, "machine_type"] = "cross"
    tab_queue_io.loc[ind_hospital, "machine_type"] = "hospital"

    tab_queue_io.loc[ind_pipeline_res, "pipeline_type"] = "pipeline_res"
    tab_queue_io.loc[~ind_pipeline_res, "pipeline_type"] = "pipeline"
    tab_queue_io.loc[ind_pipeline_replace, "pipeline_type"] = "pipeline_replace"

    line_count_last = tab_queue_io.shape[0]
    assert line_count_ori == line_count_last
    return tab_queue_io


def get_queue_io():
    """Returns a data frame: queue_io, only includes rows where normal_path == 1"""
    table = load_from_mysql('i_queue_io')
    return table[table.normal_path == 1]


def get_equipment_process_time():
    """
    Returns the processing time corresponding to the equipment, which may not necessarily be linked to resources.
    samples:
        {'a1_1': 0.0,
         'a1_10': 0.0,
         'a1_11': 0.0,
         'a1_12': 0.0,
         'a1_2': 0.0,
         'a1_3': 0.0,}
    """
    table = get_base_equipment_io()
    table_dict = table.groupby(["equipment_port"])["process_time"].apply(lambda x: list(x)[0]).to_dict()

    return table_dict


def get_parameters():
    """
    返回设备参数

    samples:
      {'a1': {'prob_of_nc': 0.059999999999999998, 'vehicle_turnaround_time': 0.0},
       'a2': {'prob_of_nc': 0.059999999999999998, 'vehicle_turnaround_time': 0.0}, }
    """

    table_n = "i_equipment_parameter"
    table = load_from_mysql(table_n)

    # change parameter name
    table["parameter_id"] = table["parameter_id"].replace(
        {'uld_turnaround_time': 'vehicle_turnaround_time',
         'truck_turnaround_time': 'vehicle_turnaround_time', })

    table_dict = \
        table.groupby(["equipment_id"])["parameter_id", "parameter_value"] \
            .apply(lambda x: x.groupby("parameter_id")["parameter_value"]\
                   .apply(lambda x: list(x)[0]).to_dict()).to_dict()

    return table_dict


def get_equipment_store_dict():
    """返回共享队列的设备和 store 代码的对应关系

    {('m2_1', 'j10_1'): {'max_time': 141.63, 'store_id': 'J_1'},
     ('m2_1', 'j12_1'): {'max_time': 141.63, 'store_id': 'J_1'},
     ('m2_1', 'j14_1'): {'max_time': 141.63, 'store_id': 'J_1'},
     ('m2_1', 'j16_1'): {'max_time': 141.63, 'store_id': 'J_1'},
     ('m2_1', 'j18_1'): {'max_time': 141.63, 'store_id': 'J_1'},
     }

    """
    table = load_from_mysql('i_queue_io')

    u_table = table[table.equipment_port_next.str.startswith('u')]
    j_table = table[table.equipment_port_next.str.startswith('j')]

    g_u_size = u_table.groupby('equipment_port_last').size()
    g_j_size = j_table.groupby('equipment_port_last').size()

    # 保证至少有2个替代的节点
    equipment_ports_u = g_u_size[g_u_size > 1].index
    equipment_ports_j = g_j_size[g_j_size > 1].index

    u_table = u_table[u_table.equipment_port_last.isin(equipment_ports_u)]
    j_table = j_table[j_table.equipment_port_last.isin(equipment_ports_j)]

    equipment_store_dict = dict()
    names = ['equipment_port_next', 'process_time']

    for idx, (k, v) in enumerate(u_table.groupby('equipment_port_last')[names].apply(dict).to_dict().items(), start=1):
        max_p_time = v['process_time'].max()
        for p in v['equipment_port_next']:
            equipment_store_dict[(k, p)] = dict(store_id=f'U_{idx}', max_time=max_p_time)

    for idx, (k, v) in enumerate(j_table.groupby('equipment_port_last')[names].apply(dict).to_dict().items(), start=1):
        max_p_time = v['process_time'].max()
        for p in v['equipment_port_next']:
            equipment_store_dict[(k, p)] = dict(store_id=f'J_{idx}', max_time=max_p_time)

    return equipment_store_dict


def get_base_equipment_io_max():
    """得到 i_equipment_io 基础表格 开始时间最大"""
    table = load_from_mysql("i_equipment_io")
    base_table = table[table.start_time == table.start_time.max()]
    return base_table


def get_base_equipment_io():
    """得到 i_equipment_io 基础表格"""
    table = load_from_mysql("i_equipment_io")
    base_table = table[table.start_time == table.start_time.min()]
    return base_table


def get_base_resource_limit():
    """得到 i_resource_limit 基础表格"""
    table = load_from_mysql("i_resource_limit")
    base_table = table[table.start_time == table.start_time.min()]
    return base_table


def clean_end_time(x):
    """保持最后的状态直到共产主义消失为止"""
    if x.shape[0] > 1:
        x['end_time'] = list(x['start_time'])[1:] + [np.inf]
    else:
        x['end_time'] = np.inf
    return x


def get_resource_timetable():
    """返回资源被占用改变的时间表， 资源被占用发生改变将生成 process 占用资源，模拟资源变化的情况

    资源被占用 = 最大资源 - 目标资源数

    """
    table = load_from_mysql('i_resource_limit')
    # clean resource_limit, no zero
    table.resource_limit = table.resource_limit.mask(table.resource_limit == 0, table.resource_number)
    table['resource_occupy'] = table['resource_number'] - table['resource_limit']

    g_resource = table.sort_values('start_time').groupby('resource_id')
    table_resource_occupy_change = g_resource.apply(lambda x: x[x.resource_occupy.diff() != 0]).reset_index(drop=True)

    # convert to seconds
    table_resource_occupy_change["start_time"] = \
        (pd.to_datetime(table_resource_occupy_change["start_time"]) - TimeConfig.ZERO_TIMESTAMP) \
            .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)

    table_resource_occupy_change["end_time"] = \
        (pd.to_datetime(table_resource_occupy_change["end_time"]) - TimeConfig.ZERO_TIMESTAMP) \
            .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)
    # 保持最后的状态直到共产主义消失为止
    table_resource_occupy_change = table_resource_occupy_change.groupby('resource_id').apply(clean_end_time)
    return table_resource_occupy_change


def get_equipment_timetable():
    """返回机器开机的时间表字典
    """
    table = load_from_mysql('i_equipment_io')
    g_equipment = table.sort_values('start_time').groupby('equipment_port')
    table_equipment_change = g_equipment.apply(lambda x: x[x.equipment_status.diff() != 0]).reset_index(drop=True)

    # convert to seconds
    table_equipment_change["start_time"] = \
        (pd.to_datetime(table_equipment_change["start_time"]) - TimeConfig.ZERO_TIMESTAMP) \
            .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)

    table_equipment_change["end_time"] = \
        (pd.to_datetime(table_equipment_change["end_time"]) - TimeConfig.ZERO_TIMESTAMP) \
            .apply(lambda x: x.total_seconds() if x.total_seconds() > 0 else 0)

    # 保持最后的状态直到共产主义消失为止
    table_equipment_change = table_equipment_change.groupby('equipment_port').apply(clean_end_time)

    # 只保留关机的状态
    table_temp = table_equipment_change[table_equipment_change.equipment_status == 1]
    equipment_open_time = defaultdict(list)

    for idx, row in table_temp.set_index('equipment_port').iterrows():
        equipment_open_time[idx].append((row['start_time'], row['end_time']))

    switch_machine_names = ['r', 'a', 'u', 'j']

    return equipment_open_time, switch_machine_names


def get_equipment_on_off():
    """
    返回初始设备的开关信息, 返回开的设备名

    samples:
        on: ['r1_1', 'r1_2', ..]
        off: ['r2_1', 'r3_3', ..]
    """
    table = get_base_equipment_io()
    equipment_on = table[table.equipment_status == 1]
    equipment_off = table[table.equipment_status == 0]
    return equipment_on.equipment_port.tolist(), equipment_off.equipment_port.tolist(),


def get_equipment_port_type():
    """Get the type of device port.

    # r, a: unload
    # m: presort
    # i1 - i8: secondary_sort
    # i17 - i24: secondary_sort
    # u1 - u8: small_primary
    # i9 - i16: small_secondary
    # c5 - c12: small_reload
    # j: security
    # h: hospital
    # e, x: cross
    # c1 - c4: reload
    # c13 - c18: reload


    {'cross': ['e1_1','e2_1','e3_1','e4_1','e5_1','e6_1','x10_1','x11_1','x12_1',
               'x13_1','x14_1','x15_1','x16_1','x17_1','x1_1','x2_1','x3_1','x4_1',
               'x5_1','x6_1','x7_1','x8_1','x9_1'],

     'hospital': ['h1_1', 'h2_1', 'h3_1'], ...}

    """

    table = load_from_mysql('i_queue_io')

    all_ports = set(list(table.equipment_port_next) + list(table.equipment_port_last))

    filter_unload = lambda x: True if x[0] in ['r', 'a'] else False
    filter_presort = lambda x: True if x[0] in ['m', ] else False

    filter_secondary_sort = \
        lambda x: True if x.split('_')[0] in [f'i{x}' for x in range(1, 9)] + [f'i{x}' for x in range(17, 25)] else False

    filter_small_primary = lambda x: True if x.split('_')[0] in [f"u{x}" for x in range(1, 9)] else False
    filter_small_secondary = lambda x: True if x.split('_')[0] in [f"i{x}" for x in range(9, 17)] else False
    filter_small_reload = lambda x: True if x.split('_')[0] in [f"c{x}" for x in range(5, 13)] else False
    filter_security = lambda x: True if x[0] in ['j'] else False
    filter_hospital = lambda x: True if x[0] in ['h'] else False
    filter_cross = lambda x: True if x[0] in ['e', 'x'] else False

    filter_reload = \
        lambda x: True if x.split('_')[0] in [f'c{x}' for x in range(1, 5)] + \
                                             [f'c{x}' for x in range(13, 19)] else False
    filters = {"unload": filter_unload,
               "presort": filter_presort,
               "secondary_sort": filter_secondary_sort,
               "small_primary": filter_small_primary,
               "small_secondary": filter_small_secondary,
               "small_reload": filter_small_reload,
               "security": filter_security,
               "hospital": filter_hospital,
               "cross": filter_cross,
               "reload": filter_reload, }

    equipment_port_dict = dict()

    for name, flter in filters.items():
        equipment_port_dict[name] = sorted(list(filter(flter, all_ports)))

    # checking
    temp_list = list()
    _ = [temp_list.extend(x) for x in equipment_port_dict.values()]
    assert bool(all_ports - set(temp_list)) == False, "Not all ports are classify!!"

    return equipment_port_dict

if __name__ == "__main__":
    test = get_queue_io()
    print(test)
