from typing import Optional

import torch.distributed as dist
from torch.nn import Module
from torch.utils.data.distributed import DistributedSampler
from torch_geometric.loader import DataLoader

import sevenn._keys as KEY
from sevenn.model_build import build_E3_equivariant_model
from sevenn.sevenn_logger import Logger
from sevenn.train.trainer import Trainer


def loader_from_config(config, dataset, is_train=False):
    batch_size = config[KEY.BATCH_SIZE]
    shuffle = is_train and config[KEY.TRAIN_SHUFFLE]
    sampler = None
    if config[KEY.IS_DDP]:
        dist.barrier()
        sampler = DistributedSampler(
            dataset, dist.get_world_size(), dist.get_rank(), shuffle=shuffle
        )
    return DataLoader(dataset, batch_size, shuffle, sampler=sampler)


def train_v2(config, working_dir: str):
    """
    Main program flow, since v0.9.6
    """
    from sevenn.train.graph_dataset import from_config

    from .processing_continue import processing_continue_v2
    from .processing_epoch import processing_epoch_v2

    log = Logger()
    log.timer_start('total')

    if KEY.LOAD_TRAINSET not in config and KEY.LOAD_DATASET in config:
        log.writeline('***************************************************')
        log.writeline('For train_v2, please use load_trainset_path instead')
        log.writeline('I will assign load_trainset as load_dataset')
        log.writeline('***************************************************')
        config[KEY.LOAD_TRAINSET] = config.pop(KEY.LOAD_DATASET)

    # config updated
    start_epoch = 1
    state_dicts: Optional[list[dict]] = None
    if config[KEY.CONTINUE][KEY.CHECKPOINT]:
        state_dicts, start_epoch = processing_continue_v2(config)

    datasets = from_config(config, working_dir)
    loaders = {
        k: loader_from_config(config, v, is_train=(k == 'trainset'))
        for k, v in datasets.items()
    }

    log.write('\nModel building...\n')
    model = build_E3_equivariant_model(config)
    assert isinstance(model, Module)
    log.print_model_info(model, config)

    trainer = Trainer(model, config)
    if state_dicts:
        trainer.load_state_dicts(*state_dicts, strict=False)

    processing_epoch_v2(
        config, trainer, loaders, start_epoch, working_dir=working_dir
    )
    log.timer_end('total', message='Total wall time')


def train(config, working_dir: str):
    """
    Main program flow, until v0.9.5
    """
    from .processing_continue import processing_continue
    from .processing_dataset import processing_dataset
    from .processing_epoch import processing_epoch

    log = Logger()
    log.timer_start('total')

    # config updated
    state_dicts: Optional[list[dict]] = None
    if config[KEY.CONTINUE][KEY.CHECKPOINT]:
        state_dicts, start_epoch, init_csv = processing_continue(config)
    else:
        start_epoch, init_csv = 1, True

    # config updated
    train, valid, _ = processing_dataset(config, working_dir)
    datasets = {'dataset': train, 'validset': valid}
    loaders = {
        k: loader_from_config(config, v, is_train=(k == 'dataset'))
        for k, v in datasets.items()
    }
    loaders = list(loaders.values())

    log.write('\nModel building...\n')
    model = build_E3_equivariant_model(config)
    assert isinstance(model, Module)

    log.write('Model building was successful\n')

    trainer = Trainer(model, config)
    if state_dicts:
        trainer.load_state_dicts(*state_dicts, strict=False)

    log.print_model_info(model, config)

    log.write('Trainer initialized, ready to training\n')
    log.bar()

    processing_epoch(trainer, config, loaders, start_epoch, init_csv, working_dir)
    log.timer_end('total', message='Total wall time')
