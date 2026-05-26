from setuptools import find_packages, setup

setup(
    name="obstacle-crossing",
    version="0.1.0",
    description="Standalone obstacle crossing task library built on Isaac Lab + InstinctLab",
    packages=find_packages(include=["obstacle_crossing", "obstacle_crossing.*"]),
    include_package_data=True,
    zip_safe=False,
)
