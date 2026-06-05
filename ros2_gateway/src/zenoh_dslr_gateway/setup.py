from setuptools import find_packages, setup


package_name = "zenoh_dslr_gateway"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (
            f"share/{package_name}/launch",
            ["launch/dslr_gateway.launch.py", "launch/dual_dslr_gateway.launch.py"],
        ),
        (
            f"share/{package_name}/config",
            [
                "config/gateway.params.yaml",
                "config/canon_eos_6d.params.yaml",
                "config/canon_eos_m50.params.yaml",
            ],
        ),
    ],
    install_requires=["setuptools", "eclipse-zenoh==1.8.0", "Pillow>=9.0.0"],
    zip_safe=True,
    maintainer="OpenAI Codex",
    maintainer_email="devnull@example.com",
    description="ROS 2 relay and test harness for a Zenoh-native DSLR capture service",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "gateway_node = zenoh_dslr_gateway.gateway_node:main",
            "capture_client = zenoh_dslr_gateway.capture_client:main",
        ],
    },
)
