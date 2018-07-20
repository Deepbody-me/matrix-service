import os
import shutil
import tempfile
import time
import traceback
import loompy

from hca.util import SwaggerAPIException
from typing import List, Tuple
from abc import ABC, abstractmethod
from chalicelib import get_mtx_paths
from chalicelib.config import MERGED_MTX_BUCKET_NAME, TEMP_DIR, hca_client, \
    s3_blob_store, logger
from chalicelib.request_handler import RequestHandler, RequestStatus


class MatrixHandler(ABC):
    """
    A generic matrix handler for matrices concatenation
    """
    def __init__(self, suffix) -> None:
        self._suffix = suffix

    def _download_mtx(self, bundle_uuids: List[str]) -> Tuple[str, List[str]]:
        """
        Filter for the matrix files within bundles, and download them locally

        :param bundle_uuids: A list of bundle uuids
        :return: A list of downloaded local matrix files paths and their directory
        """
        # Create a temp directory for storing s3 matrix files
        temp_dir = tempfile.mkdtemp(dir=TEMP_DIR)

        # Filter and download only matrices file that satisfies a specific suffix within bundles
        for bundle_uuid in bundle_uuids:
            dest_name = os.path.join(temp_dir, bundle_uuid)

            try:
                logger.info("Downloading matrices from bundle, {}, into {}."
                            .format(bundle_uuid, dest_name))

                hca_client.download(
                    bundle_uuid=bundle_uuid,
                    replica="aws",
                    dest_name=dest_name,
                    metadata_files=(),
                    data_files=("*{}".format(self._suffix),)
                )

            # Catch file not found exception
            except SwaggerAPIException as e:
                raise e

        # Get all downloaded mtx paths from temp_dir
        local_mtx_paths = get_mtx_paths(temp_dir, self._suffix)

        logger.info("Done downloading %d matrix files.", len(local_mtx_paths))

        return temp_dir, local_mtx_paths

    @abstractmethod
    def _concat_mtx(self, mtx_paths: List[str], mtx_dir: str, request_id: str) -> str:
        """
        Concatenate a list of matrices, and save into a new file on disk.

        :param mtx_paths: A list of downloaded local matrix files paths.
        :param mtx_dir: The directory that contains the matrices.
        :param request_id: The request id for the matrices concatenation.
        :return: New concatenated matrix file's path.
        """

    def _upload_mtx(self, path: str) -> str:
        """
        Upload a matrix file into an s3 bucket.
        :param path: Path of the merged matrix.
        :return: S3 bucket key for uploading file.
        """
        logger.info("%s", "Uploading \"{}\" to s3 bucket: \"{}\".".format(
            os.path.basename(path),
            MERGED_MTX_BUCKET_NAME
        ))

        key = os.path.basename(path)
        with open(path, "rb") as merged_matrix:
            s3_blob_store.upload_file_handle(
                bucket=MERGED_MTX_BUCKET_NAME,
                key=key,
                src_file_handle=merged_matrix
            )

        logger.info("Done uploading.")

        # Remove local merged mtx after uploading it to s3
        shutil.rmtree(os.path.dirname(path))

        return key
class LoomMatrixHandler(MatrixHandler):
    """
    Matrix handler for .loom file format
    """
    def __init__(self) -> None:
        super().__init__(".loom")

    def _concat_mtx(self, mtx_paths: List[str], mtx_dir: str, request_id: str) -> str:
        try:
            merged_mtx_dir = tempfile.mkdtemp(dir=TEMP_DIR)
            out_file = os.path.join(merged_mtx_dir, request_id + self._suffix)
            logger.info("Combining matrices to %s.", out_file)
            loompy.combine(mtx_paths, out_file)
            logger.info("Done combining.")

        # Catch any potential exception arose from loompy.combine()
        except Exception as e:
            raise e

        # Remove all unneeded downloaded mtx at the end
        finally:
            shutil.rmtree(mtx_dir)

        return out_file
