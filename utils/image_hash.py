"""
图片 Hash 工具 - 使用 pHash 算法
"""

import io
from typing import Optional
from astrbot.api import logger

try:
    from PIL import Image
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False
    logger.warning("imagehash 库未安装，图片去重功能将不可用")


def compute_phash(image_data: bytes, hash_size: int = 16) -> Optional[str]:
    """
    计算图片的感知哈希

    Args:
        image_data: 图片二进制数据
        hash_size: 哈希大小，默认 16 (生成 256 位哈希)

    Returns:
        哈希字符串，如果失败返回 None
    """
    if not HAS_IMAGEHASH:
        return None

    try:
        img = Image.open(io.BytesIO(image_data))
        hash_value = imagehash.phash(img, hash_size=hash_size)
        return str(hash_value)
    except Exception as e:
        logger.debug(f"计算图片哈希失败: {e}")
        return None


def compute_dhash(image_data: bytes, hash_size: int = 16) -> Optional[str]:
    """
    计算图片的差异哈希

    Args:
        image_data: 图片二进制数据
        hash_size: 哈希大小

    Returns:
        哈希字符串，如果失败返回 None
    """
    if not HAS_IMAGEHASH:
        return None

    try:
        img = Image.open(io.BytesIO(image_data))
        hash_value = imagehash.dhash(img, hash_size=hash_size)
        return str(hash_value)
    except Exception as e:
        logger.debug(f"计算图片差异哈希失败: {e}")
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    计算两个哈希之间的汉明距离

    Args:
        hash1: 第一个哈希字符串
        hash2: 第二个哈希字符串

    Returns:
        汉明距离
    """
    if not HAS_IMAGEHASH:
        return -1

    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return h1 - h2
    except Exception as e:
        logger.debug(f"计算汉明距离失败: {e}")
        return -1


def is_similar(hash1: str, hash2: str, threshold: int = 10) -> bool:
    """
    判断两个哈希是否相似

    Args:
        hash1: 第一个哈希字符串
        hash2: 第二个哈希字符串
        threshold: 相似度阈值，汉明距离小于此值认为相似

    Returns:
        是否相似
    """
    distance = hamming_distance(hash1, hash2)
    if distance < 0:
        return False
    return distance <= threshold
