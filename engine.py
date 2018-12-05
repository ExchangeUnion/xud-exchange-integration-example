import decimal
import functools
import xudrpc_pb2
import xudrpc_pb2_grpc
import grpc
import _thread
import traceback
from decimal import Decimal

buy = []
sell = []
user = None

orders = []
users = []
P = 'BTC'
Q = 'LTC'
stub = None


class User:
    def __init__(self, name):
        self.name = name
        self.balance = {}
        self.orders = []


class Match:
    def __init__(self, order, quantity, price):
        self.order = order
        self.quantity = quantity
        self.price = price

    def __repr__(self):
        return "Match{order=%s, quantity=%s, price=%s}" % (self.order.id, self.quantity, self.price)


class Order:
    id = 0

    def __init__(self, user, side, quantity, price=None, extra=None):
        Order.id = Order.id + 1
        self.id = Order.id
        self.user = user
        self.side = side
        self.quantity = Decimal(quantity)
        self.original_quantity = Decimal(quantity)
        self.price = Decimal(price) if price is not None else None
        self.matches = []
        self.status = 'PENDING'
        self.reject_reason = None
        self.extra = extra

    def __repr__(self):
        return "Order{id=%s, user=%s, side=%s, quantity=%s/%s, price=%s, status=%s, reject_reason=%s, matches=%s}" % (self.id, self.user.name, self.side, self.quantity, self.original_quantity, self.price, self.status, self.reject_reason, self.matches)


alice = User('alice')
alice.balance[P] = Decimal(0)
alice.balance[Q] = Decimal(0)

bob = User('bob')
bob.balance[P] = Decimal(0)
bob.balance[Q] = Decimal(0)

xud = User('xud')

users.append(alice)
users.append(bob)


def compare_buy(a, b):
    p = decimal.Decimal.compare(b.price, a.price)
    if p == 0:
        return a.id - b.id
    return p


def compare_sell(a, b):
    p = decimal.Decimal.compare(a.price, b.price)
    if p == 0:
        return a.id - b.id
    return p


def get_peers(order):
    global buy, sell
    
    peers = []

    if order.side == 'buy':
        peers = sell
    elif order.side == 'sell':
        peers = buy
    
    return peers


def accept_price(order, price):
    if order.side == 'buy':
        return order.price >= price
    elif order.side == 'sell':
        return order.price <= price


def do_place(order):
    if order.side == 'buy':
        buy.append(order)
        sorted(buy, key=functools.cmp_to_key(compare_buy))
    elif order.side == 'sell':
        sell.append(order)
        sorted(sell, key=functools.cmp_to_key(compare_sell))
    xud_place_order(order.id, order.side, order.quantity, order.price)


def do_settlement(order):




    pass


def handle_market_order(order):
    order.status = 'OPEN'
    
    peers = get_peers(order)
    
    total = 0
    for peer in peers:
        total += peer.quantity
    if total < order.quantity:
        order.status = 'REJECTED'
        order.reject_reason = 'INSUFFICIENT_MARKET_DEPTH'
        print('Insufficient market depth')
        return
    remain = order.quantity
    while len(peers) > 0 and remain > 0:
        first = peers[0]
        if remain >= first.quantity:
            q = first.quantity
            remain = remain - first.quantity
            first.quantity = 0
            first.status = 'CLOSED'
            order.matches.append(Match(order=first, quantity=q, price=first.price))
            peers.pop(0)
        else:
            q = remain
            remain = 0
            first.quantity = first.quantity - remain
            order.matches.append(Match(order=first, quantity=q, price=first.price))

    order.quantity = remain

    order.status = 'CLOSED'

    if len(order.matches) > 0:
        do_settlement(order)

    print(order)


def handle_limit_order(order):
    global buy, sell
    order.status = 'OPEN'

    peers = get_peers(order)
    
    remain = order.quantity
    while len(peers) > 0 and remain > 0 and accept_price(order, peers[0].price):
        first = peers[0]
        if remain >= first.quantity:
            q = first.quantity
            remain = remain - first.quantity
            first.quantity = 0
            first.status = 'CLOSED'
            order.matches.append(Match(order=first, quantity=q, price=order.price))
            peers.pop(0)
        else:
            q = remain
            remain = 0
            first.quantity = first.quantity - remain
            order.matches.append(Match(order=first, quantity=q, price=order.price))

    order.quantity = remain
    
    if remain > 0:
        # maker here
        do_place(order)
    else:
        order.status = 'CLOSED'
    
    if len(order.matches) > 0:
        do_settlement(order)

    print(order)
    
    
def place_order(cmd):
    global user, orders
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    side = parts[0]
    if len(parts) < 2:
        print("Missing <quantity>[@<price>]")
        return
    qp = parts[1]
    if '@' in qp:
        nums = qp.split('@')
        order = Order(user, side, quantity=nums[0], price=nums[1])
        orders.append(order)
        handle_limit_order(order)
    else:
        order = Order(user, side, quantity=qp)
        orders.append(order)
        handle_market_order(order)
    # buy = sorted(buy, key=functools.cmp_to_key(compare_buy))


def place_xud_order(quantity, price, order_id, side, peer_pub_key, created_at):
    order = Order(xud, side, quantity, price, extra={
        "xud_order_id": order_id,
        "peer_pub_key": peer_pub_key,
        "created_at": created_at,
    })
    if price is None:
        handle_market_order(order)
    else:
        handle_limit_order(order)


def cancel_order(cmd):
    global user, orders, buy, sell
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing <orderId>")
    order_id = int(parts[1])
    result = list(filter(lambda x: x.id == order_id, orders))
    if len(result) == 0:
        print("Not found!")
        return
    target = result[0]
    if target.status == 'OPEN':
        target.status = 'CANCELLED'
        if target.side == 'buy':
            buy.remove(target)
        elif target.side == 'sell':
            sell.remove(target)
    else:
        print('Too late to cancel')
        return


def cancel_xud_order(order_id):
    pass




def print_order_entry(order):
    print('%s %s' % (order.price, order.quantity))


def print_orderbook():
    for e in reversed(sell):
        print_order_entry(e)
    print('----------------')
    for e in buy:
        print_order_entry(e)


def load_credentials():
    with open('./tls.cert', 'rb') as f:
        cert = f.read()
    return grpc.ssl_channel_credentials(root_certificates=cert)  # Need binary cert not string!


def xud_get_info():
    global stub
    request = xudrpc_pb2.GetInfoRequest()
    response = stub.GetInfo(request)
    print(response)


def xud_list_pairs():
    global stub
    request = xudrpc_pb2.ListPairsRequest()
    response = stub.ListPairs(request)
    print(response)


def xud_get_orders():
    global stub
    request = xudrpc_pb2.GetOrdersRequest(pair_id='LTC/BTC', include_own_orders=True)
    response = stub.GetOrders(request)
    print(response)


def xud_place_order(order_id, side, quantity, price):
    global stub, Q, P
    if stub is None:
        print("xud is not connected!")
        return
    xud_side = xudrpc_pb2.BUY if side == 'buy' else xudrpc_pb2.SELL
    request = xudrpc_pb2.PlaceOrderRequest(price=price, quantity=quantity, pair_id='%s/%s' % (Q, P), order_id='test-%s' % order_id, side=xud_side)
    for response in stub.PlaceOrder(request):
        print(response)


def xud_execute_swap():
    global stub
    request = xudrpc_pb2.ExecuteSwapRequest(pair_id='LTC/BTC', order_id='', peer_pub_key='', quantity='')
    response = stub.ExecuteSwap(request)
    print(response)


def subscribe_added_orders(stub):
    try:
        request = xudrpc_pb2.SubscribeAddedOrdersRequest()
        for response in stub.SubscribeAddedOrders(request):
            print("------------ADDED------------")
            print(response)
            place_xud_order(response.quantity, response.price, response.id, 'sell' if response.side == 'SELL' else 'buy', response.peer_pub_key, response.created_at)
    except:
        traceback.print_exc()


def subscribe_removed_orders(stub):
    try:
        request = xudrpc_pb2.SubscribeRemovedOrdersRequest()
        for response in stub.SubscribeRemovedOrders(request):
            print("-----------REMOVED-----------")
            print(response)
            cancel_xud_order(response.order_id)
    except:
        traceback.print_exc()


def subscribe_swaps(stub):
    try:
        request = xudrpc_pb2.SubscribeRemovedOrdersRequest()
        for response in stub.SubscribeSwaps(request):
            print("------------SWAPS------------")
            print(response)
    except:
        traceback.print_exc()


def run_subscribe_added_orders(host, port):
    with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        subscribe_added_orders(stub)


def run_subscribe_removed_orders(host, port):
    with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        subscribe_removed_orders(stub)


def run_subscribe_swaps(host, port):
    with grpc.secure_channel('%s:%s' % (host, port), load_credentials()) as channel:
        stub = xudrpc_pb2_grpc.XudStub(channel)
        subscribe_swaps(stub)


def handle_connect(cmd):
    global stub

    parts = cmd.split()
    host = parts[1] if len(parts) > 1 else 'localhost'
    port = parts[2] if len(parts) > 2 else 8886

    _thread.start_new_thread(run_subscribe_added_orders, (host, port))
    _thread.start_new_thread(run_subscribe_removed_orders, (host, port))
    _thread.start_new_thread(run_subscribe_swaps, (host, port))

    channel = grpc.secure_channel('%s:%s' % (host, port), load_credentials())
    stub = xudrpc_pb2_grpc.XudStub(channel)
    xud_get_info()
    # xud_list_pairs()
    xud_get_orders()


def handle_deposit(cmd):
    global user
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing <currency>")
        return
    if len(parts) < 3:
        print("Missing <amount>")
        return
    currency = parts[1]
    amount = parts[2]
    user.balance[currency] = user.balance[currency] + Decimal(amount)


def print_help():
    print("login <user>")
    print("logout")
    print("buy/sell <quantity>[@<price>]")
    print("cancel <orderId>")
    print("balance [<currency>]")
    print("deposit <currency> <amount>")
    print("orderbook")
    print("connect [<host>] [<port>]")
    print("help")
    print("exit")


def print_balance(cmd):
    global user
    if user is None:
        print("Login first")
        return
    parts = cmd.split()
    if len(parts) == 1:
        print(user.balance)
    else:
        print(user.balance[parts[1]])


def handle_login(cmd):
    global user
    parts = cmd.split()
    if len(parts) < 2:
        print("Missing user!")
        return
    name = parts[1]
    result = list(filter(lambda u: u.name == name, users))
    if len(result) == 0:
        print("No such user: ", name)
    user = result[0]


def print_orders(cmd):
    global user, orders
    if user is None:
        print("Login first!")
        return
    result = list(filter(lambda x: x.user == user, orders))
    for order in result:
        print(order)


def run():
    global user
    while True:
        if user is None:
            cmd = input('> ')
        else:
            cmd = input('(%s) > ' % user.name)
        if cmd == 'exit':
            break
        elif cmd.startswith('login'):
            handle_login(cmd)
        elif cmd == 'logout':
            user = None
        elif cmd.startswith('buy') or cmd.startswith('sell'):
            place_order(cmd)
        elif cmd.startswith('cancel'):
            cancel_order(cmd)
        elif cmd.startswith('balance'):
            print_balance(cmd)
        elif cmd == 'orderbook':
            print_orderbook()
        elif cmd.startswith('connect'):
            handle_connect(cmd)
        elif cmd.startswith('deposit'):
            handle_deposit(cmd)
        elif cmd.startswith('orders'):
            print_orders(cmd)
        elif cmd == 'help':
            print_help()
        else:
            print('Bad command: ' + cmd)
            print('Type `help` for some help')


if __name__ == '__main__':
    run()
