import click

@click.command()
@click.option('--pid', required=True, type=int, help='PID of the process to inspect')
def main(pid):
    print(f"Reading memory for PID {pid}...")
    with open(f"/proc/{pid}/smaps") as f:
        print(f.read())

if __name__ == '__main__':
    main()